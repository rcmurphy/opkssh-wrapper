# AGENTS.md — opkssh-py

Guide for AI agents contributing to **opkssh-py**, a thin shell shim that
transparently injects [opkssh](https://github.com/openpubkey/opkssh) into SSH
workflows. The shim intercepts `ssh` invocations, ensures a valid opkssh
identity exists, and passes all arguments through to the real `ssh` binary
unmodified.

---

## What This Project Is

A passthrough wrapper. The user aliases or injects `opkssh-py` in place of
`ssh`. The shim:

1. Checks whether a valid (non-expired) opkssh ephemeral key exists.
2. If not, triggers `opkssh login` to obtain one via OIDC.
3. Prepends the appropriate `-o IdentitiesOnly=yes -i <key_path>` flags.
4. Execs the real `ssh` binary with the user's original arguments fully
   preserved.

The shim does **not** parse SSH traffic, implement any cryptography, manage
server-side policy, or modify the user's arguments beyond injecting the
identity flags. It is intentionally minimal.

---

## Security Model

This shim occupies a privileged position: it sits between the user and `ssh`,
handles ephemeral key paths, and invokes `opkssh login` which opens a browser
and produces tokens. Agents must treat it as security-critical code despite its
small surface area.

### Argument Passthrough Integrity

The shim's core contract is that **user arguments reach `ssh` exactly as
provided**. The shim must never interpret, interpolate, re-split, or
shell-expand user arguments. This means:

- Use `os.execvp()` (or `subprocess.run` with list-form args) to hand off to
  `ssh`. The user's `argv` is forwarded as a list — never joined into a string.
- **Never use `shell=True`**, `os.system()`, or any mechanism that passes
  arguments through a shell. The shim receives pre-parsed argv from the OS and
  must keep it that way.
- The only modifications to the argument list are prepending identity flags
  (`-o IdentitiesOnly=yes`, `-i <path>`). These are constructed internally,
  never from user input.

### Locating the Real `ssh`

The shim must reliably find the actual `ssh` binary without invoking itself
recursively. Agents should be aware of the risk: if the shim is installed as
`ssh` on `$PATH`, a naive `which ssh` or `shutil.which("ssh")` will find the
shim itself, causing infinite recursion.

Strategies (choose and document one):

- Resolve the real binary at install time and store the absolute path in config.
- Walk `$PATH` entries and skip the shim's own location.
- Use a well-known path like `/usr/bin/ssh` as a fallback with config override.

Whichever approach is used, it must be tested with the shim actually installed
as `ssh` to confirm no recursion occurs.

### Key Path Handling

The shim references the ephemeral key opkssh writes (by default
`~/.ssh/id_ecdsa`). When constructing the `-i` flag:

- Resolve the path with `pathlib.Path.resolve()` and confirm it lives within
  `~/.ssh/` or `~/.opk/`. Reject anything that resolves outside these
  directories.
- Verify the private key file has mode `0o600` before passing it to `ssh`. If
  permissions are wrong, abort with a clear error rather than silently
  proceeding. `ssh` itself will refuse overly-permissive keys, but the shim
  should catch this earlier with a better message.
- Never log or display the key path's contents — only the path itself.

### opkssh Binary Invocation

When the shim calls `opkssh login`:

- Invoke as a list: `["opkssh", "login", ...]`. No shell interpolation.
- Set a timeout. The login flow opens a browser and waits for OIDC callback;
  without a timeout, a hung browser stalls the shell indefinitely.
- Capture stderr for error reporting but never log stdout, which may contain
  token material.
- If login fails, the shim must exit with a nonzero code. It must never fall
  through to `ssh` without a valid identity — that would silently downgrade to
  whatever default key or agent the user has, defeating the purpose.

### Secret Exposure

The shim itself doesn't handle tokens directly (opkssh does), but agents should
be cautious:

- Never log the contents of key files, OIDC tokens, or opkssh stdout.
- If the shim captures subprocess output for error handling, scrub or discard
  it after use. Do not include it in exception messages that might reach a
  crash reporter.
- Environment variables like `OPKSSH_PY_*` used for configuration must never
  hold secret material. Secrets live in files with restricted permissions, never
  in the environment.

### Recursive Execution & Fork Safety

Because the shim replaces `ssh` in the user's path, think about:

- `ssh`-based tools (`git`, `rsync`, `scp`, `sftp`, `ansible`) may invoke `ssh`
  as a subprocess. The shim must work correctly in these non-interactive
  contexts, which means the OIDC browser login may not be possible. The shim
  should detect non-interactive invocations and either use an existing valid key
  or fail with a clear message rather than attempting to open a browser.
- `ProxyJump` / `ProxyCommand` chains cause `ssh` to spawn nested `ssh`
  processes. The shim should handle this gracefully — the identity flags only
  need injection at the outermost layer.

---

## Documentation Standards

### Docstrings

Every module, class, and public function requires a docstring. Use Google style.
Functions that invoke subprocesses or touch the filesystem should include a
`Security:` section noting what trust assumptions they make.

### Inline Comments

Comment **why**, not what. Prefix security-relevant comments with
`# SECURITY:` so they're greppable:

```python
# SECURITY: list-form exec preserves argv integrity — no shell interpretation
os.execvp(ssh_path, [ssh_path, *identity_flags, *user_args])
```

### Type Annotations

Full type annotations on all functions. Use `from __future__ import annotations`
for modern union syntax. The project should pass `mypy --strict`.

---

## Localization (i18n)

The shim emits very few user-facing strings (login prompt, error messages, help
text), but all of them must go through gettext from the start:

```python
from opkssh_py.i18n import _

click.echo(_("Key expired. Launching opkssh login..."))
```

Rules:

- No bare user-facing strings in any module. Wrap in `_()`.
- Use named placeholders so translators can reorder:
  `_("Login timed out after {seconds}s.")` — never concatenate fragments.
- Structured log messages (for debugging, not user display) are **not**
  localized. Keep them stable and in English for grepability.

---

## Testing

### What Must Be Tested

**Argument integrity** — the highest-priority test category. Given arbitrary
`argv` inputs (including edge cases like hostnames with special characters,
multiple `-o` flags, `--` separators, quoted arguments), the arguments that
reach the real `ssh` must be exactly what the user provided, with only the
identity flags prepended:

```python
@given(args=st.lists(st.text(min_size=1), min_size=1, max_size=20))
def test_user_args_are_never_modified(args):
    """The shim must not alter, reorder, or drop user arguments."""
    ...
```

**Recursive invocation** — install the shim as `ssh` on a test `$PATH` and
confirm it finds the real binary, not itself.

**Expiry detection** — mock a stale key and confirm the shim triggers login
rather than passing an expired identity to `ssh`.

**Non-interactive mode** — simulate a `git push` or `rsync` invoking the shim
without a TTY and confirm it either uses an existing valid key or fails cleanly
without trying to open a browser.

**Permission enforcement** — create a key file with `0o644` and confirm the
shim refuses to use it.

**Login failure** — mock `opkssh login` returning a nonzero exit code and
confirm the shim exits without invoking `ssh`.

### Test Tooling

- `pytest` with `hypothesis` for property-based argument fuzzing.
- Mock the `opkssh` binary in unit tests with a simple script that writes a
  known key file.
- Integration tests should use a real `opkssh` binary where available, gated
  behind a marker (`--runslow` or similar).

### CI Gates

All PRs must pass: unit tests with ≥90% coverage on shim logic, `mypy --strict`,
`ruff` lint + format, `bandit` with zero high-severity findings, and
confirmation that all `_()` calls have `.po` catalog entries.

---

## Agent Pitfalls

| Mistake | Consequence | Prevention |
|---|---|---|
| Joining argv into a string for subprocess | Shell injection; corrupts args with spaces/quotes | Always use list-form. Never `shell=True`. |
| Using `shutil.which("ssh")` without excluding self | Infinite recursion when shim is installed as `ssh` | Skip shim's own directory when resolving |
| Opening browser in non-interactive context | Hangs `git push`, `rsync`, CI pipelines | Check for TTY; use existing key or fail |
| Falling through to `ssh` after login failure | Silent security downgrade to stale/default keys | Exit nonzero on any login error |
| Logging subprocess stdout from opkssh | Token exposure in logs | Only capture stderr; discard stdout |
| Hardcoded English error messages | Breaks i18n | Wrap all user-facing strings in `_()` |
| Injecting identity flags in the wrong argv position | Breaks user's `-o` overrides or `--` handling | Prepend flags before user args; respect `--` |
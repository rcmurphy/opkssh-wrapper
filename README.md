# opkssh-wrapper

![PyPI - Version](https://img.shields.io/pypi/v/opkssh-wrapper)
[![codecov](https://codecov.io/github/rcmurphy/opkssh-wrapper/graph/badge.svg?token=R4MROXM4R7)](https://codecov.io/github/rcmurphy/opkssh-wrapper)

A thin shim that transparently wires [opkssh](https://github.com/openpubkey/opkssh)
into your normal `ssh` workflow. Alias it as `ssh` and forget it's there — the
wrapper silently ensures your ephemeral OpenPubKey identity is fresh before
every connection, then hands all arguments through to the real `ssh` unchanged.

---

## How it works

When you run `ssh user@host`:

1. The wrapper checks whether a valid, non-expired opkssh ephemeral key exists.
2. If the key is missing or expired, it calls `opkssh login` (opens a browser
   for OIDC authentication).
3. It prepends `-o IdentitiesOnly=yes -i <key_path>` to your arguments.
4. It `exec`s the real `ssh` binary with your original arguments intact.

Your SSH experience is unchanged. Every flag, host pattern, and `~/.ssh/config`
option continues to work exactly as before.

---

## Usage

Use it exactly like `ssh`:

```sh
ssh user@host
ssh -p 2222 -A user@host
ssh -J bastion user@internal
git push origin main          # works transparently via GIT_SSH / core.sshCommand
rsync -avz src/ user@host:dst/
```

If your key has expired and a terminal is available, you will be prompted to
authenticate. In non-interactive contexts (CI, `rsync`, `git`) the wrapper
exits with an error and tells you to run `opkssh login` first.

---

## Installation

### Prerequisites

- Python 3.10 or later
- [`opkssh`](https://github.com/openpubkey/opkssh) installed and on `$PATH`

### Install the package

**pipx** (recommended — keeps the tool isolated):

```sh
pipx install opkssh-wrapper
```

**pip** (system or virtual environment):

```sh
pip install opkssh-wrapper
```

**Standalone binary** (no Python required at runtime):

Pre-built binaries may be available on the
[Releases](../../releases) page. Download, mark executable, and place on your
`$PATH`:

```sh
chmod +x opkssh-wrapper
mv opkssh-wrapper ~/.local/bin/
```

---

### Set up the shell alias

The preferred way to use opkssh-wrapper is to alias `ssh` to it so that every
SSH invocation goes through the wrapper automatically.

Choose the section for your shell below. Add the shown snippet to your shell's
startup file, then open a new terminal (or `source` the file) to activate it.

---

#### bash

Add to `~/.bashrc`:

```bash
alias ssh='opkssh-wrapper'

# Keep tab-completion working on the alias.
# bash-completion defines _ssh; redirect that spec to cover the alias name too.
if declare -F _ssh > /dev/null 2>&1; then
  complete -F _ssh ssh
fi
```

> **Note:** The `complete` line above re-binds the `_ssh` completion function
> to the alias. If bash-completion loads `_ssh` lazily (common in many
> distributions), this line is a no-op on the first shell start but will take
> effect once `_ssh` has been loaded for the first time. To force it reliably,
> load the ssh completion before the `complete` call:
>
> ```bash
> alias ssh='opkssh-wrapper'
> # Eagerly load ssh completions, then apply to the alias
> _completion_loader ssh 2>/dev/null || true
> if declare -F _ssh > /dev/null 2>&1; then
>   complete -F _ssh ssh
> fi
> ```

---

#### zsh

Add to `~/.zshrc`:

```zsh
alias ssh='opkssh-wrapper'

# Tell zsh to use ssh's completion spec for the alias.
# This must appear after compinit has run.
compdef opkssh-wrapper=ssh
```

If you use a framework such as Oh My Zsh or Prezto, place these lines
**after** the framework is sourced (e.g. after `source $ZSH/oh-my-zsh.sh`).

---

#### fish

Add to `~/.config/fish/config.fish`:

```fish
alias ssh 'opkssh-wrapper'
```

Then create a completions file so that typing `ssh <Tab>` delegates to fish's
built-in SSH completions:

```sh
mkdir -p ~/.config/fish/completions
cat > ~/.config/fish/completions/opkssh-wrapper.fish <<'EOF'
# Reuse all SSH completions for opkssh-wrapper
complete -c opkssh-wrapper -w ssh
EOF
```

Because the fish `alias` command creates a shell function named `ssh`, fish
will automatically use existing `ssh` completions when you type `ssh <Tab>`.
The completions file above additionally provides completions when you invoke
`opkssh-wrapper` directly.

To persist the alias across sessions:

```fish
funcsave ssh
```

---

### Optional: configuration file

Create `~/.config/opkssh-wrapper/config.toml` to override defaults:

```toml
# Path to the opkssh binary (default: "opkssh", resolved via $PATH)
opkssh_path = "opkssh"

# Path to the real ssh binary (default: auto-detected, skipping the shim)
# ssh_path = "/usr/bin/ssh"

# Path to the ephemeral private key written by opkssh (default: ~/.ssh/id_ecdsa)
key_path = "~/.ssh/id_ecdsa"

# How many hours a freshly-issued key is considered valid (default: 24)
key_ttl_hours = 24

# Seconds to wait for the key file to appear on disk after login (default: 10)
key_wait_timeout = 10

# Seconds before opkssh login is forcibly killed (default: 120)
login_timeout = 120

# If true, attempt browser login even in non-interactive contexts (default: false)
aggressive_login = false
```

---

## License

[LGPL-3.0](LICENSE.md)

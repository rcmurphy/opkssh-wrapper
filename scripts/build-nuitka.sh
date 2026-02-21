#!/usr/bin/env bash
# Build a standalone binary of opkssh-wrapper using Nuitka.
#
# Usage:
#   bash scripts/build-nuitka.sh
#
# Prerequisites:
#   pip install nuitka ordered-set zstandard
#   On Linux: sudo apt-get install -y patchelf gettext
#   On macOS:  brew install gettext

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LOCALE_SRC="${PROJECT_ROOT}/src/opkssh_wrapper/locale"

# Compile .po → .mo so Nuitka can bundle the binary translation catalogs.
# Use process substitution so set -e applies to the loop body.
while IFS= read -r po_file; do
    mo_file="${po_file%.po}.mo"
    msgfmt -c -o "${mo_file}" "${po_file}"
done < <(find "${LOCALE_SRC}" -name "*.po")

python -m nuitka \
    --onefile \
    --output-filename=opkssh-wrapper \
    --include-data-dir="${LOCALE_SRC}=opkssh_wrapper/locale" \
    "${PROJECT_ROOT}/src/opkssh_wrapper/main.py"

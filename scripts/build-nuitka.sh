#!/usr/bin/env bash
# Build a standalone binary of opkssh-wrapper using Nuitka.
#
# Usage:
#   bash scripts/build-nuitka.sh
#
# Prerequisites:
#   pip install nuitka ordered-set zstandard
#   On Linux: sudo apt-get install -y patchelf

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LOCALE_SRC="${PROJECT_ROOT}/src/opkssh_wrapper/locale"

python -m nuitka \
    --onefile \
    --output-filename=opkssh-wrapper \
    --include-data-dir="${LOCALE_SRC}=opkssh_wrapper/locale" \
    "${PROJECT_ROOT}/src/opkssh_wrapper/main.py"

#!/usr/bin/env bash
set -euo pipefail

uv_install_docs="https://docs.astral.sh/uv/getting-started/installation/"

if command -v uvx >/dev/null 2>&1; then
  uvx --version
  exit 0
fi

if command -v brew >/dev/null 2>&1; then
  printf 'uvx not found. Installing uv with Homebrew.\n'
  brew install uv
elif command -v curl >/dev/null 2>&1; then
  printf 'uvx not found. Installing uv with the official installer.\n'
  curl -LsSf https://astral.sh/uv/install.sh | /bin/sh
else
  printf 'uvx is required. Install uv from %s\n' "${uv_install_docs}" >&2
  exit 1
fi

export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v uvx >/dev/null 2>&1; then
  printf 'uv was installed but uvx is not on PATH. See %s\n' "${uv_install_docs}" >&2
  exit 1
fi

uvx --version

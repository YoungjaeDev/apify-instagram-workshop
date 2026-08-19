#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
setup_script="${repo_root}/scripts/setup-mcp.sh"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/apify-mcp-test.XXXXXX")"
trap '/bin/rm -rf -- "${test_root}"' EXIT

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_contains() {
  local actual="$1"
  local expected="$2"

  case "${actual}" in
    *"${expected}"*) ;;
    *) fail "expected output to contain: ${expected}" ;;
  esac
}

test_existing_uvx_is_reused() {
  local bin_dir="${test_root}/existing/bin"
  local output
  /bin/mkdir -p "${bin_dir}"

  printf '%s\n' '#!/bin/sh' 'printf "uvx 9.9.9-test\n"' > "${bin_dir}/uvx"
  /bin/chmod +x "${bin_dir}/uvx"

  output="$(PATH="${bin_dir}" /bin/bash "${setup_script}" 2>&1)" || fail "existing uvx should succeed"
  assert_contains "${output}" "uvx 9.9.9-test"
}

test_homebrew_is_first_install_fallback() {
  local bin_dir="${test_root}/brew/bin"
  local output
  /bin/mkdir -p "${bin_dir}"

  printf '%s\n' \
    '#!/bin/sh' \
    'printf "%s\n" "#!/bin/sh" "printf \"uvx 8.8.8-brew\\n\"" > "${MOCK_BIN_DIR}/uvx"' \
    '/bin/chmod +x "${MOCK_BIN_DIR}/uvx"' > "${bin_dir}/brew"
  /bin/chmod +x "${bin_dir}/brew"

  output="$(MOCK_BIN_DIR="${bin_dir}" PATH="${bin_dir}" /bin/bash "${setup_script}" 2>&1)" || fail "Homebrew fallback should succeed"
  assert_contains "${output}" "uvx 8.8.8-brew"
}

test_curl_is_second_install_fallback() {
  local bin_dir="${test_root}/curl/bin"
  local home_dir="${test_root}/curl/home"
  local output
  /bin/mkdir -p "${bin_dir}" "${home_dir}/.local/bin"

  printf '%s\n' \
    '#!/bin/sh' \
    'printf "%s\n" "#!/bin/sh" "printf \"uvx 7.7.7-curl\\n\"" > "${HOME}/.local/bin/uvx"' \
    '/bin/chmod +x "${HOME}/.local/bin/uvx"' > "${bin_dir}/curl"
  /bin/chmod +x "${bin_dir}/curl"

  output="$(HOME="${home_dir}" PATH="${bin_dir}" /bin/bash "${setup_script}" 2>&1)" || fail "curl fallback should succeed"
  assert_contains "${output}" "uvx 7.7.7-curl"
}

test_missing_installers_returns_actionable_error() {
  local bin_dir="${test_root}/missing/bin"
  local output
  /bin/mkdir -p "${bin_dir}"

  if output="$(PATH="${bin_dir}" /bin/bash "${setup_script}" 2>&1)"; then
    fail "missing installers should fail"
  fi
  assert_contains "${output}" "https://docs.astral.sh/uv/getting-started/installation/"
}

test_existing_uvx_is_reused
test_homebrew_is_first_install_fallback
test_curl_is_second_install_fallback
test_missing_installers_returns_actionable_error

printf 'PASS: setup-mcp fallback behavior\n'

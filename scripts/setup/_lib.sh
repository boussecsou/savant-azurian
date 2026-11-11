#!/usr/bin/env bash
# Shared helpers for the setup scripts. Source it; do not run it.
#
# Every script here is a dry run by default: it prints what it would do and changes nothing.
# Pass --apply to execute. Nothing here ever prints a secret.
set -euo pipefail

APPLY=0
POSITIONAL=()

parse_common_flags() {
  for arg in "$@"; do
    case "$arg" in
      --apply) APPLY=1 ;;
      -h|--help) usage; exit 0 ;;
      *) POSITIONAL+=("$arg") ;;
    esac
  done
}

# Load the active azd environment (.azure/<env>/.env) into this shell. Read-only.
load_azd_env() {
  command -v azd >/dev/null || { echo "azd is required." >&2; exit 1; }
  local line key value
  while IFS= read -r line; do
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    value="${value#\"}"
    value="${value%\"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && export "$key=$value"
  done < <(azd env get-values)
}

require() {
  local missing=0 name
  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      echo "Missing ${name}. Run 'azd provision' first, or set it with 'azd env set ${name} <value>'." >&2
      missing=1
    fi
  done
  [[ "$missing" -eq 0 ]] || exit 1
}

# run <description> <command...>: print, and execute only with --apply.
run() {
  local description="$1"
  shift
  if [[ "$APPLY" -eq 1 ]]; then
    echo "==> ${description}"
    "$@"
  else
    echo "[dry run] ${description}"
    printf '         '
    printf ' %q' "$@"
    printf '\n'
  fi
}

finish() {
  if [[ "$APPLY" -eq 0 ]]; then
    echo
    echo "Nothing was changed. Re-run with --apply to execute the steps above."
  fi
}

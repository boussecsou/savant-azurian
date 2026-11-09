#!/usr/bin/env bash
# Prepare the optional SSH tool: a dedicated key pair for the agent, and the VM's pinned host key.
#
# 1. Generates an ed25519 key pair in a temporary folder.
# 2. Stores the private key in Key Vault as 'sa2-ssh-private-key' (never printed, then deleted).
# 3. Prints the public key line to add to the VM's ~/.ssh/authorized_keys for the dedicated account.
# 4. Reads the VM's ed25519 host key with ssh-keyscan and prints the SSH_* values to set.
#
# ssh-keyscan trusts whatever answers on first contact. Compare the printed fingerprint with the one
# shown on the VM (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`) before you trust the host key.
#
#   scripts/setup/ssh-setup.sh --host <vm-ip-or-name> [--user sa2agent] [--port 22]            # dry run
#   scripts/setup/ssh-setup.sh --host <vm-ip-or-name> --apply
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$here/_lib.sh"
usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

host="" user="sa2agent" port="22" args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) host="$2"; shift 2 ;;
    --user) user="$2"; shift 2 ;;
    --port) port="$2"; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
parse_common_flags "${args[@]+"${args[@]}"}"
[[ -n "$host" ]] || { echo "--host is required." >&2; usage; exit 1; }
load_azd_env
require KEY_VAULT_NAME KEY_VAULT_URL

secret_name="sa2-ssh-private-key"

create_and_store() {
  local dir
  dir="$(mktemp -d)"
  trap 'rm -rf "$dir"' RETURN
  ssh-keygen -q -t ed25519 -N "" -C "savant-agent" -f "$dir/key"
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "$secret_name" --file "$dir/key" --encoding utf-8 --output none
  echo
  echo "Add this public key to /home/${user}/.ssh/authorized_keys on the VM:"
  cat "$dir/key.pub"
}

scan_host_key() {
  local key
  key="$(ssh-keyscan -t ed25519 -p "$port" "$host" 2>/dev/null | grep -v '^#' | head -n 1 | cut -d' ' -f2-)"
  [[ -n "$key" ]] || { echo "No ed25519 host key answered on ${host}:${port}." >&2; exit 1; }
  echo
  echo "Fingerprint to compare with the one on the VM:"
  printf '%s\n' "$key" | ssh-keygen -lf -
  echo
  echo "Then set (all five, or none to keep the SSH tool off):"
  echo "  azd env set SSH_HOST ${host}"
  echo "  azd env set SSH_USER ${user}"
  echo "  azd env set SSH_HOST_KEY '${key}'"
  echo "  azd env set SSH_KEY_VAULT_URL ${KEY_VAULT_URL}"
  echo "  azd env set SSH_KEY_SECRET_NAME ${secret_name}"
}

run "Generate an ed25519 key pair and store the private key as '${secret_name}' in ${KEY_VAULT_NAME}" create_and_store
run "Read the host key of ${host}:${port}" scan_host_key
finish

#!/usr/bin/env bash
# Create the Notion OAuth encryption key in Key Vault, once.
#
# The key encrypts the Notion tokens stored in Blob Storage. It is generated here, written straight
# to the vault and never printed, never stored in a file you keep, never put in an environment
# variable. It is not overwritten if the secret already exists: rotating it would make the stored
# tokens unreadable and force a new Notion consent.
#
# Needs: Azure CLI signed in, the azd environment holding KEY_VAULT_NAME, and the Key Vault Secrets
# Officer role on the vault.
#   scripts/setup/generate-notion-key.sh            # dry run
#   scripts/setup/generate-notion-key.sh --apply
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$here/_lib.sh"
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }
parse_common_flags "$@"
load_azd_env
require KEY_VAULT_NAME

secret_name="notion-oauth-encryption-key"

if [[ "$APPLY" -eq 1 ]] && az keyvault secret show --vault-name "$KEY_VAULT_NAME" --name "$secret_name" --query id -o tsv >/dev/null 2>&1; then
  echo "Secret '${secret_name}' already exists in ${KEY_VAULT_NAME}: left untouched."
  exit 0
fi

store_key() {
  local file
  file="$(mktemp)"
  trap 'rm -f "$file"' RETURN
  chmod 600 "$file"
  # 32 random bytes, URL-safe base64: the format of a Fernet key.
  python3 -c 'import base64, os, sys; sys.stdout.write(base64.urlsafe_b64encode(os.urandom(32)).decode())' >"$file"
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "$secret_name" --file "$file" --encoding utf-8 --output none
}

run "Generate a 32-byte key and store it as secret '${secret_name}' in ${KEY_VAULT_NAME}" store_key
finish

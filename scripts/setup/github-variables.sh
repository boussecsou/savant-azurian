#!/usr/bin/env bash
# Copy the deployment values from the azd environment to GitHub repository variables, for CI/CD.
#
# These are configuration, not secrets: GitHub signs in to Azure with OpenID Connect, so no Azure
# secret is ever stored. Empty values are skipped. Names are explained in docs/configuration.md.
#
#   scripts/setup/github-variables.sh --repo <owner>/<name>            # dry run
#   scripts/setup/github-variables.sh --repo <owner>/<name> --apply
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$here/_lib.sh"
usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

repo="" args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
parse_common_flags "${args[@]+"${args[@]}"}"
[[ "$repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || { echo "--repo must look like owner/name." >&2; usage; exit 1; }
load_azd_env
require OIDC_CLIENT_ID AZURE_TENANT_ID AZURE_SUBSCRIPTION_ID AZURE_LOCATION

# GitHub variable <- azd environment variable
declare -a pairs=(
  "AZURE_CLIENT_ID=OIDC_CLIENT_ID"
  "AZURE_TENANT_ID=AZURE_TENANT_ID"
  "AZURE_SUBSCRIPTION_ID=AZURE_SUBSCRIPTION_ID"
  "AZURE_LOCATION=AZURE_LOCATION"
  "AZURE_AI_PROJECT_ENDPOINT=AZURE_AI_PROJECT_ENDPOINT"
  "AZURE_AI_PROJECT_ID=AZURE_AI_PROJECT_ID"
  "AZURE_OPENAI_BASE_URL=AZURE_OPENAI_BASE_URL"
  "AZURE_AI_MODEL_DEPLOYMENT_NAME=AZURE_AI_MODEL_DEPLOYMENT_NAME"
  "TOOLBOX_ENDPOINT=TOOLBOX_ENDPOINT"
  "NOTION_OAUTH_CALLBACK_URL=NOTION_OAUTH_CALLBACK_URL"
  "NOTION_OAUTH_STORE_URL=NOTION_OAUTH_STORE_URL"
  "KEY_VAULT_URL=KEY_VAULT_URL"
  "NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID=NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID"
  "NOTION_OWNER_ID=NOTION_OWNER_ID"
  "SEARCH_ENDPOINT=SEARCH_ENDPOINT"
  "SSH_HOST=SSH_HOST"
  "SSH_USER=SSH_USER"
  "SSH_HOST_KEY=SSH_HOST_KEY"
  "SSH_KEY_VAULT_URL=SSH_KEY_VAULT_URL"
  "SSH_KEY_SECRET_NAME=SSH_KEY_SECRET_NAME"
  "ACR_NAME=ACR_NAME"
)

for pair in "${pairs[@]}"; do
  github_name="${pair%%=*}"
  azd_name="${pair#*=}"
  value="${!azd_name:-}"
  if [[ -z "$value" ]]; then
    echo "[skip] ${github_name}: ${azd_name} is empty"
    continue
  fi
  run "Set GitHub variable ${github_name}" gh variable set "$github_name" --repo "$repo" --body "$value"
done
finish

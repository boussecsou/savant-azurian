#!/usr/bin/env bash
# Grant the roles that cannot exist before the first agent deployment.
#
# The hosted agent gets its own identity when `azd deploy` creates it, so the Bicep template cannot
# name it. Find its object (principal) ID in the Foundry portal (the agent's identity) or in the
# output of `azd ai agent show`, then:
#
#   scripts/setup/grant-agent-roles.sh --agent-principal-id <object-id>            # dry run
#   scripts/setup/grant-agent-roles.sh --agent-principal-id <object-id> --apply
#
# Agent identity:  Key Vault Secrets User (vault), Storage Blob Data Contributor (notion-oauth
#                  container), Search Index Data Reader (search), Cognitive Services OpenAI User,
#                  Monitoring Metrics Publisher (Application Insights: without it the agent's
#                  traces and live metrics are refused with `Forbidden`).
# BFF identity:    Foundry Agent Consumer, so the BFF may call the agent. Granted on the project:
#                  narrow it to the agent itself in the portal if you want strict least privilege.
#
# Afterwards set the agent's client ID (same page) for the Notion token store and redeploy:
#   azd env set NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID <client-id>
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$here/_lib.sh"
usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; }

agent="" args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-principal-id) agent="$2"; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
parse_common_flags "${args[@]+"${args[@]}"}"
[[ "$agent" =~ ^[0-9a-fA-F-]{36}$ ]] || { echo "--agent-principal-id must be a GUID." >&2; usage; exit 1; }
load_azd_env
require AZURE_RESOURCE_GROUP KEY_VAULT_NAME APP_INSIGHTS_NAME FOUNDRY_ACCOUNT_NAME STORAGE_ACCOUNT_NAME SEARCH_SERVICE_NAME \
  BFF_IDENTITY_PRINCIPAL_ID AZURE_AI_PROJECT_ID AZURE_SUBSCRIPTION_ID

base="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers"
vault_scope="${base}/Microsoft.KeyVault/vaults/${KEY_VAULT_NAME}"
container_scope="${base}/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}/blobServices/default/containers/notion-oauth"
search_scope="${base}/Microsoft.Search/searchServices/${SEARCH_SERVICE_NAME}"
account_scope="${base}/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT_NAME}"
insights_scope="${base}/Microsoft.Insights/components/${APP_INSIGHTS_NAME}"

grant() { # grant <principal> <role> <scope>
  az role assignment create --assignee-object-id "$1" --assignee-principal-type ServicePrincipal \
    --role "$2" --scope "$3" --output none
}

run "Agent: Key Vault Secrets User on the vault" grant "$agent" "Key Vault Secrets User" "$vault_scope"
run "Agent: Storage Blob Data Contributor on the notion-oauth container" grant "$agent" "Storage Blob Data Contributor" "$container_scope"
run "Agent: Search Index Data Reader on the search service" grant "$agent" "Search Index Data Reader" "$search_scope"
run "Agent: Cognitive Services OpenAI User on the Foundry account" grant "$agent" "Cognitive Services OpenAI User" "$account_scope"
run "Agent: Monitoring Metrics Publisher on Application Insights" grant "$agent" "Monitoring Metrics Publisher" "$insights_scope"
run "BFF: Foundry Agent Consumer on the Foundry project" grant "$BFF_IDENTITY_PRINCIPAL_ID" "Foundry Agent Consumer" "$AZURE_AI_PROJECT_ID"
finish

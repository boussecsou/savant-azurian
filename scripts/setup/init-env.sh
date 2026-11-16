#!/usr/bin/env bash
# Create and fill the azd environment for a new deployment, in one step.
#
# Sets the values that only you can provide: the environment name, the Azure region, the subscription,
# a fixed owner key for the Notion token store (a new UUID), your Entra object ID (the owner the backend
# accepts) and, optionally, the GitHub repository allowed to deploy. Nothing is sent to Azure: this only
# writes to your local azd environment (.azure/<name>/.env, ignored by Git).
#
#   scripts/setup/init-env.sh --name savant-dev --location <region>                       # dry run
#   scripts/setup/init-env.sh --name savant-dev --location <region> [--subscription <id>] \
#       [--github-repo <owner>/<name>] --apply
#
# With --apply it asks the Azure CLI for your subscription and object ID (you must be signed in with `az login`).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$here/_lib.sh"
usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

name="" location="" subscription="" repo="" args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) name="$2"; shift 2 ;;
    --location) location="$2"; shift 2 ;;
    --subscription) subscription="$2"; shift 2 ;;
    --github-repo) repo="$2"; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
parse_common_flags "${args[@]+"${args[@]}"}"
[[ "$name" =~ ^[a-z][a-z0-9-]{1,30}$ ]] || { echo "--name must be 2 to 31 characters: lowercase letters, digits and hyphens, starting with a letter." >&2; usage; exit 1; }
[[ -n "$location" ]] || { echo "--location is required (an Azure region, for example italynorth)." >&2; usage; exit 1; }
[[ -z "$repo" || "$repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || { echo "--github-repo must look like owner/name." >&2; exit 1; }
command -v azd >/dev/null || { echo "azd is required: https://aka.ms/install-azd" >&2; exit 1; }

if [[ "$APPLY" -eq 1 ]]; then
  command -v az >/dev/null || { echo "az is required with --apply to read your subscription and object ID." >&2; exit 1; }
  [[ -n "$subscription" ]] || subscription="$(az account show --query id -o tsv)"
  object_id="$(az ad signed-in-user show --query id -o tsv)"
  owner_key="$(python3 -c 'import uuid; print(uuid.uuid4())')"
else
  subscription="${subscription:-<your subscription id>}"
  object_id="<your Entra object id>"
  owner_key="<a new UUID>"
fi

run "Create the azd environment '${name}'" azd env new "$name" --no-prompt
run "Select the region" azd env set AZURE_LOCATION "$location" -e "$name"
run "Select the subscription" azd env set AZURE_SUBSCRIPTION_ID "$subscription" -e "$name"
run "Set the fixed owner key (shared by the agent and the backend)" azd env set NOTION_OWNER_ID "$owner_key" -e "$name"
run "Set the owner the backend accepts (your Entra object ID)" azd env set BFF_OWNER_OBJECT_ID "$object_id" -e "$name"
if [[ -n "$repo" ]]; then
  run "Allow GitHub Actions of ${repo} to deploy (OIDC, main branch only)" azd env set OIDC_GITHUB_REPOSITORY "$repo" -e "$name"
fi
finish
[[ "$APPLY" -eq 1 ]] && echo "Next: azd provision --preview, then follow docs/deployment.md from step 2."
exit 0

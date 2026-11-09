#!/usr/bin/env bash
# Called only after a successful main CI and Azure OIDC login.
set -euo pipefail
: "${ACR_NAME:?}" "${IMAGE_REPOSITORY:?}" "${SOURCE_SHA:?}" "${GITHUB_OUTPUT:?}" "${GITHUB_STEP_SUMMARY:?}"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo '::error::Invalid source SHA'; exit 1; }
[[ "$IMAGE_REPOSITORY" == sa2-bff ]] || exit 1
sha_tag="sha-$SOURCE_SHA"
registry="$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)"
[[ "$registry" == *.azurecr.io ]] || { echo '::error::Invalid registry address'; exit 1; }
remote="$registry/$IMAGE_REPOSITORY"
az acr login --name "$ACR_NAME" --only-show-errors

error_file="$(mktemp)"
trap 'rm -f "$error_file"' EXIT
if ! tags="$(az acr repository show-tags --name "$ACR_NAME" --repository "$IMAGE_REPOSITORY" --detail -o json 2>"$error_file")"; then
  # Only the explicit missing-repository response permits the initial push.
  # Auth, network, RBAC and other failures must never mean "tag absent".
  if grep -Fq "repository \"$IMAGE_REPOSITORY\" is not found" "$error_file"; then
    tags='[]'
  else
    cat "$error_file" >&2
    exit 1
  fi
fi
expected="$(jq -r --arg tag "$sha_tag" '.[] | select(.name == $tag) | .digest' <<< "$tags")"
v1_digest="$(jq -r '.[] | select(.name == "v1") | .digest' <<< "$tags")"
if [[ "${PUBLISH_V1:-false}" == true && -n "$v1_digest" && "$v1_digest" != "$expected" ]]; then
  echo '::error::v1 already exists for another image; refusing to overwrite it.'
  exit 1
fi

if [[ -z "$expected" ]]; then
  docker tag sa2-bff:publish "$remote:$sha_tag"
  docker push "$remote:$sha_tag"
  expected="$(docker image inspect "$remote:$sha_tag" --format '{{json .RepoDigests}}' |
    jq -er --arg prefix "$remote@" '[.[] | select(startswith($prefix)) | split("@")[1]] | unique | if length == 1 then .[0] else error("ambiguous digest") end')"
fi
[[ "$expected" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo '::error::Invalid image digest'; exit 1; }
# Retries reuse the original image; mutable upstream base images cannot replace it.
docker pull "$remote@$expected"
revision="$(docker image inspect "$remote@$expected" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
[[ "$revision" == "$SOURCE_SHA" ]] || { echo '::error::Remote image source SHA mismatch'; exit 1; }

tags_to_lock=("$sha_tag")
if [[ "${PUBLISH_V1:-false}" == true ]]; then
  if [[ -z "$v1_digest" ]]; then
    docker tag "$remote@$expected" "$remote:v1"
    docker push "$remote:v1"
  fi
  tags_to_lock+=(v1)
fi
for tag in "${tags_to_lock[@]}"; do
  actual="$(az acr repository show --name "$ACR_NAME" --image "$IMAGE_REPOSITORY:$tag" --query digest -o tsv)"
  [[ "$actual" == "$expected" ]] || { echo "::error::Digest mismatch for $tag"; exit 1; }
  az acr repository update --name "$ACR_NAME" --image "$IMAGE_REPOSITORY:$tag" \
    --write-enabled false --delete-enabled false --only-show-errors -o none
  az acr repository show --name "$ACR_NAME" --image "$IMAGE_REPOSITORY:$tag" -o json |
    jq -e --arg digest "$expected" '.digest == $digest and .changeableAttributes.writeEnabled == false and .changeableAttributes.deleteEnabled == false' > /dev/null
done
# Protect the content manifest as well as the named references.
az acr repository update --name "$ACR_NAME" --image "$IMAGE_REPOSITORY@$expected" \
  --write-enabled false --delete-enabled false --only-show-errors -o none
az acr repository show --name "$ACR_NAME" --image "$IMAGE_REPOSITORY@$expected" -o json |
  jq -e '.changeableAttributes.writeEnabled == false and .changeableAttributes.deleteEnabled == false' > /dev/null
printf 'digest=%s\n' "$expected" >> "$GITHUB_OUTPUT"
{
  printf '### BFF publié et vérifié\n\n'
  printf -- '- Commit : `%s`\n- Image : `%s:%s`\n- Digest : `%s@%s`\n' "$SOURCE_SHA" "$remote" "$sha_tag" "$remote" "$expected"
  printf -- '- Références verrouillées : `%s`\n' "${tags_to_lock[*]}"
} >> "$GITHUB_STEP_SUMMARY"

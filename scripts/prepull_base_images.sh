#!/usr/bin/env bash
# Pre-pull every image the VayuSetu Compose stack needs, with retries.
#
# `docker compose up --build` fails with `lookup registry-1.docker.io: no such
# host` / `failed to compute cache key` when the Docker VM cannot resolve or
# reach the registry; build containers then re-download ~120 MB of base-image
# layers per target and abort halfway through. Pulling first (with retries)
# puts the layers in the local image store, and with DOCKER_BUILDKIT=0 Compose
# does not even resolve tags against the registry.
#
#   ./scripts/prepull_base_images.sh
#   DOCKER_BUILDKIT=0 docker compose up --build
#
# Re-run after changing a FROM line, or with --no-cache after `builder prune`.
set -uo pipefail

attempts="${PULL_ATTEMPTS:-3}"
sleep_seconds="${PULL_SLEEP:-10}"
no_cache=()
if [[ "${1:-}" == "--no-cache" ]]; then
  no_cache=(--no-cache)
  shift
fi

# Keep in sync with the FROM lines in */Dockerfile and the image: keys in
# docker-compose.yml.
images=(
  node:20-bookworm-slim          # api-gateway, firebase emulator
  node:20-alpine                 # mock-twilio, mock-google-ai
  python:3.10-slim               # functions/*, prediction-service
  fsouza/fake-gcs-server:1.56.1  # gcs
  curlimages/curl:8.10.1         # scheduler
)

failed=()
for image in "${images[@]}"; do
  pulled=0
  for ((i = 1; i <= attempts; i++)); do
    printf '\n\033[36m── docker pull %s  (attempt %d/%d)\033[0m\n' "$image" "$i" "$attempts"
    if docker pull "${no_cache[@]}" "$image"; then
      pulled=1
      break
    fi
    sleep "$sleep_seconds"
  done
  [[ "$pulled" -eq 1 ]] || failed+=("$image")
done

if ((${#failed[@]} > 0)); then
  printf '\n\033[31mFAILED after %d attempts: %s\033[0m\n' "$attempts" "${failed[*]}"
  cat <<'MSG'
Registry DNS is unreachable from the Docker VM. In Docker Desktop:
  Settings -> Resources -> Proxies: fill BOTH Web Proxy (HTTP) and
  Secure Web Proxy (HTTPS), or clear both if only HTTP was set.
  Settings -> Resources -> Network -> DNS server: 8.8.8.8, 1.1.1.1
Then restart Docker Desktop and re-run this script.
MSG
  exit 1
fi

printf '\n\033[32mAll base images available locally.\033[0m\n'
echo 'Next:  DOCKER_BUILDKIT=0 docker compose up --build'
echo '       (or plain `docker compose up --build` once DNS is healthy)'

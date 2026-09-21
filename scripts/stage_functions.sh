#!/usr/bin/env bash
# Stage a Cloud Function directory for deployment.
#
# Cloud Functions (2nd gen) uploads a single source directory, so the shared
# vayusetu_common package is vendored into a build copy of each function
# before `gcloud functions deploy --source` runs. Tests, caches and local
# configuration are excluded from the staged directory.
#
# Usage: scripts/stage_functions.sh <function_dir> [<function_dir> ...]
#        scripts/stage_functions.sh --all
#
# Output: build/functions/<function_dir>/

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FUNCTIONS_ROOT="${REPO_ROOT}/functions"
COMMON_PACKAGE="${FUNCTIONS_ROOT}/common/vayusetu_common"
BUILD_ROOT="${REPO_ROOT}/build/functions"

log() {
  printf '[stage_functions] %s\n' "$*" >&2
}

stage_one() {
  local name="$1"
  local source_dir="${FUNCTIONS_ROOT}/${name}"
  local target_dir="${BUILD_ROOT}/${name}"

  if [[ ! -f "${source_dir}/main.py" ]]; then
    log "error: ${source_dir} does not contain main.py"
    return 1
  fi
  if [[ ! -f "${source_dir}/requirements.txt" ]]; then
    log "error: ${source_dir} does not contain requirements.txt"
    return 1
  fi

  rm -rf "${target_dir}"
  mkdir -p "${target_dir}"

  # Copy function source, excluding development-only files.
  (
    cd "${source_dir}"
    find . -type f \
      ! -path './tests/*' \
      ! -name 'conftest.py' \
      ! -path '*/__pycache__/*' \
      ! -name '*.pyc' \
      ! -name '.env*' \
      -print0
  ) | (cd "${source_dir}" && xargs -0 -I{} cp --parents "{}" "${target_dir}/")

  # Vendor the shared package.
  mkdir -p "${target_dir}/vayusetu_common"
  (
    cd "${COMMON_PACKAGE}"
    find . -type f -name '*.py' ! -path '*/__pycache__/*' -print0
  ) | (cd "${COMMON_PACKAGE}" && xargs -0 -I{} cp --parents "{}" "${target_dir}/vayusetu_common/")

  # Make sure the shared package's runtime dependencies are present.
  {
    cat "${source_dir}/requirements.txt"
    printf '\n# --- vendored vayusetu_common dependencies ---\n'
    grep -Ev '^\s*(#|$)' "${FUNCTIONS_ROOT}/common/requirements.txt"
  } | awk '!seen[$0]++' > "${target_dir}/requirements.txt"

  cat > "${target_dir}/.gcloudignore" <<'IGNORE'
.gcloudignore
.git
.gitignore
__pycache__/
*.pyc
tests/
conftest.py
IGNORE

  log "staged ${name} -> ${target_dir} ($(find "${target_dir}" -type f | wc -l | tr -d ' ') files)"
}

main() {
  if [[ $# -eq 0 ]]; then
    log "usage: $0 <function_dir> [...] | --all"
    exit 2
  fi

  local targets=()
  if [[ "$1" == "--all" ]]; then
    while IFS= read -r dir; do
      targets+=("$(basename "${dir}")")
    done < <(find "${FUNCTIONS_ROOT}" -mindepth 1 -maxdepth 1 -type d ! -name common | sort)
  else
    targets=("$@")
  fi

  mkdir -p "${BUILD_ROOT}"
  for target in "${targets[@]}"; do
    stage_one "${target}"
  done
}

main "$@"

#!/usr/bin/env bash
#
# Deployment configuration preflight.
#
# Reports which GitHub Actions variables a deployment target still needs, so the
# deployment job that depends on it can be SKIPPED instead of failing. A checkout
# without Google Cloud credentials - a fork, a fresh clone, a repository that has
# not been bootstrapped with Terraform yet - is a normal state, not an error, and
# a red check for it hides real failures.
#
# This script therefore exits 0 for missing configuration and reserves a non-zero
# exit for a usage error. The strict gate lives in check_deploy_config.sh, which
# runs inside the deployment job once this preflight reports the target ready.
#
# Usage:
#   deployment_preflight.sh <target> [<target> ...]
#   targets: gateway prediction functions frontend terraform
#
# Writes the following to $GITHUB_OUTPUT when that variable is set:
#   <target>_configured   "true" when every variable the target needs is present
#   <target>_missing      comma-separated names of the variables it still needs
#   any_configured        "true" when at least one requested target is ready
#
# Writes a markdown block to $GITHUB_STEP_SUMMARY when that variable is set.
#
# Variable *values* are never printed or exported - only names.

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: deployment_preflight.sh <target> [<target> ...]
Targets: gateway prediction functions frontend terraform
EOF
}

# The variables each deployment target reads through `vars.*` in its workflow job,
# including the two every target needs to authenticate. Keep in step with
# scripts/check_deploy_config.sh and docs/BUILD_AND_DEPLOY.md.
required_variables() {
  case "$1" in
    gateway)
      printf '%s\n' \
        GCP_PROJECT_ID \
        GCP_WORKLOAD_IDENTITY_PROVIDER \
        GCP_DEPLOYER_SERVICE_ACCOUNT \
        ARTIFACT_REGISTRY
      ;;
    prediction)
      printf '%s\n' \
        GCP_PROJECT_ID \
        GCP_WORKLOAD_IDENTITY_PROVIDER \
        GCP_DEPLOYER_SERVICE_ACCOUNT \
        ARTIFACT_REGISTRY \
        ML_ARTIFACTS_BUCKET
      ;;
    functions)
      printf '%s\n' \
        GCP_PROJECT_ID \
        GCP_WORKLOAD_IDENTITY_PROVIDER \
        GCP_DEPLOYER_SERVICE_ACCOUNT \
        CITIZEN_IMAGES_BUCKET \
        ALERT_AUDIO_BUCKET \
        PREDICTION_SERVICE_URL
      ;;
    frontend)
      printf '%s\n' \
        GCP_PROJECT_ID \
        GCP_WORKLOAD_IDENTITY_PROVIDER \
        GCP_DEPLOYER_SERVICE_ACCOUNT
      ;;
    terraform)
      printf '%s\n' \
        GCP_PROJECT_ID \
        GCP_WORKLOAD_IDENTITY_PROVIDER \
        GCP_TERRAFORM_SERVICE_ACCOUNT \
        TF_STATE_BUCKET \
        ADMIN_DOMAIN
      ;;
    *)
      return 1
      ;;
  esac
}

# "A,B" -> "`A`, `B`", for the step summary table.
tick_list() {
  local item out="" IFS=','
  for item in $1; do
    out="${out}${out:+, }\`${item}\`"
  done
  printf '%s' "${out}"
}

if (( $# == 0 )); then
  usage
  exit 2
fi

targets=()
for target in "$@"; do
  if ! required_variables "${target}" >/dev/null 2>&1; then
    echo "Unknown deployment target: ${target}" >&2
    usage
    exit 2
  fi
  targets+=("${target}")
done

any_configured=false
union_missing=()
summary_rows=()
output_lines=()

for target in "${targets[@]}"; do
  configured=true
  missing=()
  while IFS= read -r name; do
    value="${!name:-}"
    if [[ -z "${value//[[:space:]]/}" ]]; then
      configured=false
      missing+=("${name}")
      if [[ ! " ${union_missing[*]-} " == *" ${name} "* ]]; then
        union_missing+=("${name}")
      fi
    fi
  done < <(required_variables "${target}")

  # Bash 4.4+ joins an empty array to "" under `set -u`; keep it explicit anyway.
  missing_csv="${missing[*]-}"
  missing_csv="${missing_csv// /,}"

  if [[ "${configured}" == "true" ]]; then
    any_configured=true
    summary_rows+=("| \`${target}\` | ready | |")
    printf '%-11s ready\n' "${target}"
  else
    summary_rows+=("| \`${target}\` | skipped | $(tick_list "${missing_csv}") |")
    printf '%-11s skipped, missing %s\n' "${target}" "${missing_csv}"
  fi

  output_lines+=("${target}_configured=${configured}")
  output_lines+=("${target}_missing=${missing_csv}")
done

union_csv="${union_missing[*]-}"
union_csv="${union_csv// /,}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf '%s\n' "${output_lines[@]}" "any_configured=${any_configured}" >>"${GITHUB_OUTPUT}"
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### Deployment preflight"
    echo ""
    echo "| Target | Status | Missing Actions variables |"
    echo "| --- | --- | --- |"
    printf '%s\n' "${summary_rows[@]}"
    echo ""
    if [[ "${any_configured}" == "true" ]] && (( ${#union_missing[@]} == 0 )); then
      echo "Every requested target is configured; its deployment job will run."
    else
      echo "Deployment jobs whose target is not ready are **skipped, not failed**: an"
      echo "unconfigured repository is a normal state and should not report a red check."
      echo "Populate the missing variables with \`terraform output github_repository_variables\`,"
      echo "then re-run this workflow - see [docs/BUILD_AND_DEPLOY.md](docs/BUILD_AND_DEPLOY.md)."
    fi
  } >>"${GITHUB_STEP_SUMMARY}"
fi

if (( ${#union_missing[@]} > 0 )); then
  echo "::warning::Deployment configuration is incomplete. Missing Actions variables: ${union_csv}. The jobs that need them are skipped instead of failing; see docs/BUILD_AND_DEPLOY.md."
else
  echo "::notice::All requested deployment targets are configured."
fi

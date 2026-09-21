#!/usr/bin/env bash
# Fail before OIDC authentication with actionable names, never variable values.
set -euo pipefail

required=(GCP_PROJECT_ID GCP_WORKLOAD_IDENTITY_PROVIDER)
case "${1:-}" in
  gateway) required+=(GCP_DEPLOYER_SERVICE_ACCOUNT ARTIFACT_REGISTRY) ;;
  prediction) required+=(GCP_DEPLOYER_SERVICE_ACCOUNT ARTIFACT_REGISTRY ML_ARTIFACTS_BUCKET) ;;
  functions) required+=(GCP_DEPLOYER_SERVICE_ACCOUNT CITIZEN_IMAGES_BUCKET ALERT_AUDIO_BUCKET PREDICTION_SERVICE_URL) ;;
  frontend) required+=(GCP_DEPLOYER_SERVICE_ACCOUNT) ;;
  terraform) required+=(GCP_TERRAFORM_SERVICE_ACCOUNT TF_STATE_BUCKET ADMIN_DOMAIN) ;;
  *) echo "Usage: $0 {gateway|prediction|functions|frontend|terraform}" >&2; exit 2 ;;
esac

missing=0
for name in "${required[@]}"; do
  value="${!name:-}"
  if [[ -z "${value//[[:space:]]/}" ]]; then
    echo "::error::Missing Actions variable ${name}. Configure repository/environment variables; see docs/BUILD_AND_DEPLOY.md."
    missing=1
  fi
done
if (( missing )); then
  echo "Bootstrap GCP with local Terraform first; GitHub OIDC cannot create its own initial identity provider." >&2
  exit 1
fi

echo "Required deployment variables are present (cloud permissions are checked by authentication/deployment)."

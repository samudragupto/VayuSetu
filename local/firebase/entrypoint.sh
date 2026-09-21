#!/usr/bin/env bash
# Starts the Firebase Local Emulator Suite with the VayuSetu event bridge.
set -euo pipefail

PROJECT_ID="${GCLOUD_PROJECT:-vayusetu-local}"
EXPORT_DIR="${EMULATOR_EXPORT_DIR:-/workspace/local/firebase/data}"

cd /workspace

if [ ! -d local/event-bridge/node_modules ]; then
  echo "[firebase] installing event bridge dependencies"
  npm --prefix local/event-bridge install --no-audit --no-fund
fi

mkdir -p "${EXPORT_DIR}"

ARGS=(emulators:start --project "${PROJECT_ID}" --only auth,firestore,functions,hosting,storage)
if [ -n "$(ls -A "${EXPORT_DIR}" 2>/dev/null)" ]; then
  ARGS+=(--import "${EXPORT_DIR}")
fi
if [ "${EMULATOR_EXPORT_ON_EXIT:-true}" = "true" ]; then
  ARGS+=(--export-on-exit "${EXPORT_DIR}")
fi

echo "[firebase] starting emulators for project ${PROJECT_ID}"
exec firebase "${ARGS[@]}"

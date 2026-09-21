#!/bin/sh
# Starts the Firebase Local Emulator Suite with the VayuSetu event bridge.
#
# Two deliberate hardenings for Windows checkouts:
#  - `#!/bin/sh` instead of `#!/usr/bin/env bash`: the kernel execs /bin/sh
#    directly, so a stray carriage return cannot turn the interpreter name into
#    "sh\r" (that is what `env bash` died from: /usr/bin/env: 'bash\r').
#  - every statement on one line, so a CRLF copy still parses: POSIX shells treat
#    the trailing CR in `<line>\r\n` as ordinary trailing whitespace when it ends a
#    complete command, but a multi-line construct (`if ... ; then` continued) makes
#    the parser see "then\r" as the command and fail. Keep it single-line, keep it
#    repairable.
# The repair for a *directly executed* CRLF copy lives outside this file: the
# `command` in docker-compose.yml strips CRs from the bind-mounted working copy
# (and from the image copy) before exec'ing it, and local/firebase/Dockerfile
# sanitises the copy baked into the image. A CRLF file cannot self-repair when it
# is exec'd - the kernel rejects `#!/bin/sh\r` before any code runs - so the
# guard below only covers being run as `sh entrypoint.sh`.
# .gitattributes (`* text=auto eol=lf`) prevents CRLF at checkout; once the working
# copy is LF, every one of these steps is a no-op.

if grep -q "$(printf '\r')" "$0" 2>/dev/null; then
  echo "[firebase] CRLF line endings detected in $0; normalising"
  VAYUSETU_TMP_LF="/tmp/vayusetu-entrypoint.$$.lf"
  tr -d '\r' < "$0" > "$VAYUSETU_TMP_LF"
  exec /bin/sh "$VAYUSETU_TMP_LF" "$@"
fi

set -eu

PROJECT_ID="${GCLOUD_PROJECT:-vayusetu-local}"
EXPORT_DIR="${EMULATOR_EXPORT_DIR:-/workspace/local/firebase/data}"

cd /workspace

if [ ! -d local/event-bridge/node_modules ]; then
  echo "[firebase] installing event bridge dependencies"
  npm --prefix local/event-bridge install --no-audit --no-fund
fi

mkdir -p "${EXPORT_DIR}"

# sh has no arrays, so build the argument list with positional parameters.
set -- emulators:start --project "${PROJECT_ID}" --only auth,firestore,functions,hosting,storage
if [ -n "$(find "${EXPORT_DIR}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
  set -- "$@" --import "${EXPORT_DIR}"
fi
if [ "${EMULATOR_EXPORT_ON_EXIT:-true}" = "true" ]; then
  set -- "$@" --export-on-exit "${EXPORT_DIR}"
fi

echo "[firebase] starting emulators for project ${PROJECT_ID}"
exec firebase "$@"

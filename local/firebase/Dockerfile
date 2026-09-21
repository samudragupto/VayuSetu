# Firebase Local Emulator Suite (Auth, Firestore, Functions, Hosting, Storage)
# packaged for docker-compose. The repository root is mounted at /workspace so
# firebase.json, the rules files, the event bridge and the built dashboard are
# all available to the emulators.
FROM node:20-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    FIREBASE_TOOLS_VERSION=13.35.1 \
    npm_config_fetch_retries=5 \
    npm_config_fetch_timeout=300000

RUN apt-get update -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global --no-audit --no-fund "firebase-tools@${FIREBASE_TOOLS_VERSION}" \
    && npm cache clean --force

WORKDIR /workspace
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# Windows checkouts can hand Git CRLF instead of LF, and an image built from such a
# tree bakes those CRs into a layer, so sanitise the copy stored in the image. This
# runs at build time and is independent of the host's core.autocrlf; the runtime
# `command` in docker-compose.yml does the same for the bind-mounted working copy.
RUN tr -d '\r' < /usr/local/bin/entrypoint.sh > /usr/local/bin/entrypoint.sh.lf \
    && mv /usr/local/bin/entrypoint.sh.lf /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 4000 4400 4500 5000 5001 8080 9099 9150 9199 9299
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

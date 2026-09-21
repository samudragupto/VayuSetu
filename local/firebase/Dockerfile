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

# Belt and braces for Windows checkouts: a CRLF copy of this script (the
# repository root is mounted over /workspace, so the mounted file is what
# actually runs) fails as `/usr/bin/env: 'bash\r': No such file or directory`.
# .gitattributes pins the endings, and this strips any stray CR anyway.
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 4000 4400 4500 5000 5001 8080 9099 9150 9199 9299
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Firebase Local Emulator Suite (Auth, Firestore, Functions, Hosting, Storage)
# packaged for docker-compose. The repository root is mounted at /workspace so
# firebase.json, the rules files, the event bridge and the built dashboard are
# all available to the emulators.
FROM node:20-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    FIREBASE_TOOLS_VERSION=13.35.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global "firebase-tools@${FIREBASE_TOOLS_VERSION}" \
    && npm cache clean --force

WORKDIR /workspace
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 4000 4400 4500 5000 5001 8080 9099 9150 9199 9299
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# syntax=docker/dockerfile:1.7
# Multi-stage build for the VayuSetu API gateway (Cloud Run, Node.js 20).
#
# The runtime stages use node:20-bookworm-slim (Debian) rather than the Alpine
# variant. Alpine 3.21+ publishes its APKINDEX in the new v2 format, which the
# apk shipped in older Docker Desktop / BuildKit VMs cannot parse; a failed
# index fetch then surfaces as a misleading "tini (no such package)" build
# error. Debian also shares its base image with the local Firebase emulator
# image, so one layer download serves both builds.
#
# There is no runtime package install at all: everything the image needs ships
# in the base. That keeps `docker compose build` working on a network where the
# distro CDN is slow or unreachable. tini was removed for the same reason -
# `docker compose` forwards SIGTERM/SIGINT straight to PID 1 (services/api-gateway
# src/index.ts installs handlers for both) and Cloud Run's sandbox reaps
# orphaned processes natively, so an in-image init binary is unnecessary here.

FROM node:20-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi

FROM deps AS build
COPY tsconfig.json tsconfig.build.json ./
COPY src ./src
RUN npm run build

FROM node:20-bookworm-slim AS prod-deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev --no-audit --no-fund; else npm install --omit=dev --no-audit --no-fund; fi \
    && npm cache clean --force

FROM node:20-bookworm-slim AS runtime
ENV NODE_ENV=production \
    PORT=8080
WORKDIR /app
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
USER node
EXPOSE 8080
# node ships everywhere this image runs; wget/curl do not exist in the slim
# Debian base, so the probe is a one-liner against the global fetch in Node 20
# (the image's ENV PORT, or 8080 when unset, so Compose never interpolates it).
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:'+(process.env.PORT||'8080')+'/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "dist/index.js"]

FROM node:20-alpine

# Retry budget for flaky CDNs: a slow registry should slow the build down, not
# fail it. (node:20-alpine is fine here - these stages never run `apk add`.)
ENV npm_config_fetch_retries=5 \
    npm_config_fetch_timeout=300000

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY server.js ./
ENV PORT=4020
EXPOSE 4020
USER node
CMD ["node", "server.js"]

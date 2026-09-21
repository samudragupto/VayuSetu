FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY server.js ./
ENV PORT=4020
EXPOSE 4020
USER node
CMD ["node", "server.js"]

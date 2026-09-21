FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY server.js ./
COPY media ./media
ENV PORT=4010
EXPOSE 4010
USER node
CMD ["node", "server.js"]

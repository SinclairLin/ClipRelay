FROM node:20-alpine

WORKDIR /app/src

COPY src/package.json src/package-lock.json* ./
RUN (npm ci --omit=dev || npm install --omit=dev)

COPY src/relay.js ./

ENV NODE_ENV=production
ENV PORT=8080

EXPOSE 8080
CMD ["node", "relay.js"]


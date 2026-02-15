FROM node:20-alpine

WORKDIR /app
COPY src/package.json src/package-lock.json* ./src/
RUN cd src && (npm ci --omit=dev || npm install --omit=dev)

COPY src/relay.js ./src/

ENV NODE_ENV=production
ENV PORT=8080

EXPOSE 8080
CMD ["node", "src/relay.js"]


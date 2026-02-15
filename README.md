# ClipRelay

Clipboard relay with:
- `server`: Node.js relay (`/push` + `/ws`)
- `client`: Python WebSocket clipboard client
- `tests`: unit and integration test scripts

## Structure

```text
client/
  config/
  src/
  requirements.txt
server/
  config/
  src/
  package.json
docker/
  Dockerfile
  compose.yml
```

## Quick Start

### Server

node
```bash
cd server
npm install
RELAY_TOKEN=REPLACE_WITH_STRONG_TOKEN PORT=8080 node src/relay.js
```

docker compose
```bash
cd docker

cat > .env <<'EOF'
PORT=8080
RELAY_TOKEN=REPLACE_WITH_STRONG_TOKEN
# ROOM_TOKENS=roomA:tokenA,roomB:tokenB
EOF

# Build and launch
docker compose -f compose.yml up --build -d

# Health check
curl -s http://127.0.0.1:8080/healthz
```

### Client

```bash
pip install -r client/requirements.txt
python client/src/cp_client.py
```



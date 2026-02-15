import express from "express";
import { WebSocketServer } from "ws";
import http from "http";
import crypto from "crypto";


const PORT = Number(process.env.PORT || 8080);

const JSON_LIMIT = process.env.JSON_LIMIT || "32kb";

const WS_HEARTBEAT_INTERVAL_MS = Number(process.env.WS_HEARTBEAT_INTERVAL_MS || 20_000);
const WS_CLIENT_TIMEOUT_MS = Number(process.env.WS_CLIENT_TIMEOUT_MS || 45_000);

const PUSH_RATE_LIMIT_PER_MIN = Number(process.env.PUSH_RATE_LIMIT_PER_MIN || 60);

const RELAY_TOKEN = (process.env.RELAY_TOKEN || "").trim();

const ROOM_TOKENS = parseRoomTokens(process.env.ROOM_TOKENS || "");

const LOG_DEBUG = String(process.env.LOG_DEBUG || "0") === "1";


const app = express();
app.use(express.json({ limit: JSON_LIMIT }));

const server = http.createServer(app);


const wss = new WebSocketServer({
  server,
  maxPayload: 64 * 1024,
});

const rooms = new Map();

const lastPongAt = new WeakMap();


function now() {
  return new Date().toISOString();
}

function maskRoom(room) {
  if (!room) return "room:<empty>";
  const h = crypto.createHash("sha256").update(room).digest("hex").slice(0, 8);
  return `room#${h}`;
}

function logInfo(msg, meta = {}) {
  console.log(`[${now()}] INFO  ${msg}${formatMeta(meta)}`);
}

function logWarn(msg, meta = {}) {
  console.warn(`[${now()}] WARN  ${msg}${formatMeta(meta)}`);
}

function logError(msg, meta = {}) {
  console.error(`[${now()}] ERROR ${msg}${formatMeta(meta)}`);
}

function logDebug(msg, meta = {}) {
  if (!LOG_DEBUG) return;
  console.log(`[${now()}] DEBUG ${msg}${formatMeta(meta)}`);
}

function formatMeta(meta) {
  const keys = Object.keys(meta || {});
  if (!keys.length) return "";
  const safe = { ...meta };
  if ("text" in safe) delete safe.text;
  if ("payload" in safe) delete safe.payload;
  return " " + JSON.stringify(safe);
}


function verifyToken(room, token) {
  const expected = ROOM_TOKENS[room];
  if (expected) return token === expected;
  if (RELAY_TOKEN) return token === RELAY_TOKEN;
  return false;
}

function authMode() {
  const hasRoomTokens = Object.keys(ROOM_TOKENS).length > 0;
  if (hasRoomTokens) return "room-tokens";
  if (RELAY_TOKEN) return "global-token";
  return "disabled";
}

function parseRoomTokens(raw) {
  const out = {};
  const items = String(raw)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  for (const item of items) {
    const idx = item.indexOf(":");
    if (idx <= 0) continue;
    const room = item.slice(0, idx).trim();
    const tok = item.slice(idx + 1).trim();
    if (!room || !tok) continue;
    out[room] = tok;
  }
  return out;
}


function joinRoom(roomKey, ws) {
  if (!rooms.has(roomKey)) rooms.set(roomKey, new Set());
  rooms.get(roomKey).add(ws);

  ws.on("close", () => {
    const set = rooms.get(roomKey);
    if (set) {
      set.delete(ws);
      if (set.size === 0) rooms.delete(roomKey);
    }
  });

  ws.on("error", (err) => {
    logWarn("ws error", { room: maskRoom(roomKey), err: String(err?.message || err) });
  });
}

function countClients(roomKey) {
  const set = rooms.get(roomKey);
  return set ? set.size : 0;
}


function getClientIp(req) {
  const xff = req.headers["x-forwarded-for"];
  const realIp = req.headers["x-real-ip"];
  const cfIp = req.headers["cf-connecting-ip"];

  if (cfIp) return String(cfIp);

  if (typeof xff === "string" && xff.length > 0) {
    return xff.split(",")[0].trim();
  }
  if (typeof realIp === "string" && realIp.length > 0) return realIp.trim();

  return req.socket?.remoteAddress || "unknown";
}

const rateBucket = new Map(); // Map<ip, {count, resetAt}>

function rateLimitOrThrow(ip) {
  const nowMs = Date.now();
  const entry = rateBucket.get(ip);

  if (!entry || nowMs >= entry.resetAt) {
    rateBucket.set(ip, { count: 1, resetAt: nowMs + 60_000 });
    return;
  }

  entry.count += 1;
  if (entry.count > PUSH_RATE_LIMIT_PER_MIN) {
    const retryAfterSec = Math.ceil((entry.resetAt - nowMs) / 1000);
    const err = new Error("RATE_LIMIT");
    err.statusCode = 429;
    err.retryAfterSec = retryAfterSec;
    throw err;
  }
}

setInterval(() => {
  const nowMs = Date.now();
  for (const [ip, entry] of rateBucket.entries()) {
    if (nowMs >= entry.resetAt) rateBucket.delete(ip);
  }
}, 60_000).unref();

// ---------------------------
// WebSocket：订阅端点 /ws?room=xxx&token=yyy
// ---------------------------

wss.on("connection", (ws, req) => {
  try {
    const url = new URL(req.url, "http://localhost");
    const room = url.searchParams.get("room") || "";
    const token = url.searchParams.get("token") || "";
    const ip = getClientIp(req);

    if (!room || !verifyToken(room, token)) {
      logWarn("ws auth failed", { ip, room: maskRoom(room), mode: authMode() });
      ws.close(1008, "auth failed"); // 1008 = Policy Violation
      return;
    }

    // 标记心跳时间
    lastPongAt.set(ws, Date.now());

    ws.on("pong", () => {
      lastPongAt.set(ws, Date.now());
    });

    joinRoom(room, ws);

    // 只记录：连接成功、房间摘要、在线数
    logInfo("ws connected", { ip, room: maskRoom(room), clients: countClients(room) });

    ws.send(JSON.stringify({ ok: true, msg: "connected" }));
  } catch (e) {
    logError("ws connection handler exception", { err: String(e?.message || e) });
    try {
      ws.close(1011, "server error"); // 1011 = Internal Error
    } catch {}
  }
});

// 心跳巡检：超时的连接强制断开，避免假在线
setInterval(() => {
  const nowMs = Date.now();

  for (const ws of wss.clients) {
    const t = lastPongAt.get(ws);
    if (!t) continue;

    if (nowMs - t > WS_CLIENT_TIMEOUT_MS) {
      // 超时断开
      try {
        ws.terminate();
      } catch {}
      continue;
    }

    try {
      ws.ping();
    } catch {}
  }
}, WS_HEARTBEAT_INTERVAL_MS).unref();

// ---------------------------
// HTTP：推送端点 POST /push  JSON {room, token, text}
// ---------------------------

app.post("/push", (req, res) => {
  const ip = getClientIp(req);

  try {
    rateLimitOrThrow(ip);

    const { room, token, text } = req.body || {};

    if (!room || !token || !verifyToken(String(room), String(token))) {
      logWarn("push auth failed", { ip, room: maskRoom(String(room || "")), mode: authMode() });
      return res.status(401).json({ ok: false });
    }

    const payloadText = String(text ?? "");
    const payload = JSON.stringify({ text: payloadText });

    const set = rooms.get(String(room));
    if (!set || set.size === 0) {
      logInfo("push accepted (no clients)", {
        ip,
        room: maskRoom(String(room)),
        text_len: payloadText.length,
        delivered: 0,
      });
      return res.json({ ok: true, delivered: 0 });
    }

    let delivered = 0;
    for (const ws of set) {
      if (ws.readyState === ws.OPEN) {
        ws.send(payload);
        delivered++;
      }
    }

    logInfo("push delivered", {
      ip,
      room: maskRoom(String(room)),
      text_len: payloadText.length,
      delivered,
      clients: set.size,
    });

    return res.json({ ok: true, delivered });
  } catch (e) {
    if (e?.message === "RATE_LIMIT") {
      res.setHeader("Retry-After", String(e.retryAfterSec || 60));
      logWarn("push rate limited", { ip, retry_after_sec: e.retryAfterSec || 60 });
      return res.status(429).json({ ok: false, error: "rate_limited" });
    }

    logError("push handler exception", { ip, err: String(e?.message || e) });
    return res.status(500).json({ ok: false });
  }
});


app.get("/healthz", (_req, res) => res.status(200).send("ok"));


server.listen(PORT, "0.0.0.0", () => {
  logInfo("relay started", {
    port: PORT,
    auth_mode: authMode(),
    json_limit: JSON_LIMIT,
    ws_heartbeat_ms: WS_HEARTBEAT_INTERVAL_MS,
    ws_timeout_ms: WS_CLIENT_TIMEOUT_MS,
    push_rate_limit_per_min: PUSH_RATE_LIMIT_PER_MIN,
    rooms_configured: Object.keys(ROOM_TOKENS).length,
  });

  if (authMode() === "disabled") {
    logWarn("auth is disabled: set RELAY_TOKEN or ROOM_TOKENS for production use");
  }
});


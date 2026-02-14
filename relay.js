import express from "express";
import { WebSocketServer } from "ws";
import http from "http";

const PORT = process.env.PORT || 8080;

const app = express();
app.use(express.json({ limit: "32kb" }));

const server = http.createServer(app);
const wss = new WebSocketServer({ server });

const rooms = new Map();

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
}

// WS: /ws?room=xxx&token=yyy
wss.on("connection", (ws, req) => {
  const url = new URL(req.url, "http://localhost");
  const room = url.searchParams.get("room") || "";
  const token = url.searchParams.get("token") || "";

  // 简单鉴权：token 必须等于 room（你可改成更强）
  if (!room || token !== room) {
    ws.close();
    return;
  }

  joinRoom(room, ws);
  ws.send(JSON.stringify({ ok: true, msg: "connected" }));
});

// iOS POST: /push  JSON {room, token, text}
app.post("/push", (req, res) => {
  const { room, token, text } = req.body || {};
  if (!room || !token || token !== room) return res.status(401).json({ ok: false });

  const set = rooms.get(room);
  if (!set || set.size === 0) return res.json({ ok: true, delivered: 0 });

  const payload = JSON.stringify({ text: String(text ?? "") });
  let delivered = 0;

  for (const ws of set) {
    if (ws.readyState === ws.OPEN) {
      ws.send(payload);
      delivered++;
    }
  }

  res.json({ ok: true, delivered });
});

app.get("/healthz", (_, res) => res.status(200).send("ok"));

server.listen(PORT, "0.0.0.0");


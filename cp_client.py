import asyncio
import json
import os
import re
import time
import websockets
import pyperclip

BASE = os.environ.get("CP_BASE", "cp.sinclairl.com")
ROOM = os.environ.get("CP_ROOM", "YOUR_ROOM_KEY")
TOKEN = os.environ.get("CP_TOKEN", ROOM)

WS_URL = f"wss://{BASE}/ws?room={ROOM}&token={TOKEN}"

# 是否在控制台打印（默认只打印状态，不打印内容）
VERBOSE = os.environ.get("CP_VERBOSE", "0") == "1"

def extract_code(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    m = re.search(r"\b(\d{4,8})\b", text)
    return m.group(1) if m else text

def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

async def run():
    retry = 1
    while True:
        try:
            log(f"Connecting: wss://{BASE}/ws (room hidden)")
            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=64 * 1024,
            ) as ws:
                log("Connected ✅")
                retry = 1

                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        raw = str(data.get("text", ""))
                    except Exception:
                        raw = str(msg)

                    code = extract_code(raw)
                    if code:
                        pyperclip.copy(code)
                        if VERBOSE:
                            log(f"Clipboard updated: {code!r}")
                        else:
                            log("Clipboard updated")

        except Exception as e:
            log(f"Disconnected, retry in {retry}s... ({type(e).__name__})")
            await asyncio.sleep(retry)
            retry = min(retry * 2, 30)

if __name__ == "__main__":
    asyncio.run(run())

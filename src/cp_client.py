import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import websockets
import pyperclip

# ---------- config loading (config.json > env > defaults) ----------

def load_config() -> tuple[dict, str]:
    """
    返回: (config_dict, loaded_path_str)
    """
    candidates = []

    # 1) exe directory (PyInstaller / frozen)
    if getattr(sys, "frozen", False):
        try:
            candidates.append(Path(sys.executable).resolve().parent / "config.json")
        except Exception:
            pass

    try:
        candidates.append(Path(__file__).resolve().parent / "config.json")
    except Exception:
        pass

    candidates.append(Path.cwd() / "config.json")

    for cfg_path in candidates:
        try:
            if cfg_path.exists():
                with cfg_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data, str(cfg_path)
                return {}, str(cfg_path)
        except Exception:
            continue

    return {}, ""

_cfg, _cfg_path = load_config()

def pick(key: str, env_key: str, default):
    """
    Priority: config.json[key] -> env[env_key] -> default
    """
    if key in _cfg and _cfg[key] is not None and str(_cfg[key]).strip() != "":
        return _cfg[key]
    v = os.environ.get(env_key)
    if v is not None and str(v).strip() != "":
        return v
    return default

BASE = str(pick("base", "CP_BASE", "example.com"))
ROOM = str(pick("room", "CP_ROOM", "YOUR_ROOM_KEY"))
TOKEN = str(pick("token", "CP_TOKEN", ROOM))

# 支持 ws/wss：config.json 里可设 use_tls=true/false 或 scheme="ws"/"wss"
use_tls_raw = _cfg.get("use_tls", None)
scheme_raw = _cfg.get("scheme", None)

if isinstance(scheme_raw, str) and scheme_raw.lower() in ("ws", "wss"):
    SCHEME = scheme_raw.lower()
elif isinstance(use_tls_raw, bool):
    SCHEME = "wss" if use_tls_raw else "ws"
else:
    # 兼容旧行为：默认 wss
    SCHEME = "wss"

WS_URL = f"{SCHEME}://{BASE}/ws?room={ROOM}&token={TOKEN}"

# 是否在控制台打印（默认只打印状态，不打印内容）
verbose_val = pick("verbose", "CP_VERBOSE", "0")
VERBOSE = str(verbose_val) == "1" or str(verbose_val).lower() in ("true", "yes", "y", "on")

# ---------- business logic ----------

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
    log(f"Config: {_cfg_path if _cfg_path else 'NOT FOUND'}")
    while True:
        try:
            log(f"Connecting: {SCHEME}://{BASE}/ws (room hidden)")
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


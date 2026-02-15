import asyncio
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pyperclip
import websockets

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

    try:
        candidates.append(Path(__file__).resolve().parent.parent / "config" / "config.json")
    except Exception:
        pass

    candidates.append(Path.cwd() / "config.json")
    candidates.append(Path.cwd() / "client" / "config" / "config.json")

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
VERBOSE = str(verbose_val).lower() in ("1", "true", "yes", "y", "on")

# 托盘模式：默认开启（Windows exe 下生效）
tray_val = pick("tray", "CP_TRAY", "1")
TRAY_ENABLED = str(tray_val).lower() in ("1", "true", "yes", "y", "on")


# ---------- business logic ----------


def extract_code(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    # Prefer digits near OTP-related keywords (Chinese + English).
    keyword = (
        r"(?:验证码|校验码|动态码|短信码|登录码|提取码|"
        r"otp|passcode|verification\s*code|security\s*code|one[-\s]*time\s*(?:password|passcode)?|code)"
    )
    m = re.search(rf"{keyword}\D{{0,20}}(?<!\d)(\d{{4,8}})(?!\d)", text, flags=re.IGNORECASE)
    if not m:
        m = re.search(rf"(?<!\d)(\d{{4,8}})(?!\d)\D{{0,20}}{keyword}", text, flags=re.IGNORECASE)
    if not m:
        # Fallback: first 4-8 digits not adjacent to other digits.
        m = re.search(r"(?<!\d)(\d{4,8})(?!\d)", text)
    return m.group(1) if m else text


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


class ClientRunner:
    def __init__(self):
        self.stop_event = threading.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ws = None
        self.thread: threading.Thread | None = None
        self._status = "idle"
        self._status_lock = threading.Lock()

    def set_status(self, status: str):
        with self._status_lock:
            self._status = status

    def get_status(self) -> str:
        with self._status_lock:
            return self._status

    async def run(self):
        retry = 1
        log(f"Config: {_cfg_path if _cfg_path else 'NOT FOUND'}")
        while not self.stop_event.is_set():
            try:
                self.set_status("connecting")
                log(f"Connecting: {SCHEME}://{BASE}/ws (room hidden)")
                async with websockets.connect(
                    WS_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=64 * 1024,
                ) as ws:
                    self.ws = ws
                    self.set_status("connected")
                    log("Connected")
                    retry = 1

                    async for msg in ws:
                        if self.stop_event.is_set():
                            break
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

                    self.ws = None

                    if self.stop_event.is_set():
                        break

                    close_code = getattr(ws, "close_code", None)
                    close_reason = getattr(ws, "close_reason", None) or ""
                    self.set_status("disconnected")
                    log(
                        f"Connection closed by server (code={close_code}, reason={close_reason!r}), retry in {retry}s..."
                    )
                    await asyncio.to_thread(self.stop_event.wait, retry)
                    retry = min(retry * 2, 30)

            except Exception as e:
                if self.stop_event.is_set():
                    break
                self.ws = None
                self.set_status("error")
                log(f"Disconnected, retry in {retry}s... ({type(e).__name__})")
                await asyncio.to_thread(self.stop_event.wait, retry)
                retry = min(retry * 2, 30)

        self.set_status("stopped")

    async def _shutdown_ws(self):
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:
            pass

    def start_in_thread(self):
        def worker():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self.run())
            finally:
                self.loop.close()

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 5.0):
        self.stop_event.set()
        if self.loop and self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown_ws(), self.loop)
            try:
                future.result(timeout=timeout)
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=timeout)


def run_with_tray():
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        log("Tray dependencies unavailable, fallback to console mode")
        asyncio.run(ClientRunner().run())
        return

    runner = ClientRunner()
    runner.start_in_thread()

    def build_image():
        image = Image.new("RGB", (64, 64), color=(25, 118, 210))
        draw = ImageDraw.Draw(image)
        draw.rectangle((18, 14, 46, 50), outline=(255, 255, 255), width=4)
        draw.rectangle((24, 8, 40, 16), outline=(255, 255, 255), width=4)
        return image

    def status_label(_item):
        return f"Status: {runner.get_status()}"

    def on_exit(icon, _item):
        runner.stop()
        icon.stop()

    icon = pystray.Icon(
        "ClipRelayClient",
        build_image(),
        "ClipRelayClient",
        menu=pystray.Menu(
            pystray.MenuItem(status_label, None, enabled=False),
            pystray.MenuItem("Exit", on_exit),
        ),
    )
    icon.run()


def main():
    is_windows = sys.platform.startswith("win")
    is_frozen = getattr(sys, "frozen", False)
    if is_windows and is_frozen and TRAY_ENABLED:
        run_with_tray()
    else:
        asyncio.run(ClientRunner().run())


if __name__ == "__main__":
    main()

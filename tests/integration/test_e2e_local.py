from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "server"
CLIENT_SRC_DIR = ROOT / "client" / "src"
CLIENT_CFG = ROOT / "client" / "config" / "config.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run local end-to-end test: relay server + cp_client + test_push_api."
    )
    p.add_argument("--port", type=int, default=8080, help="local relay port")
    p.add_argument("--room", default="testroom", help="test room name")
    p.add_argument("--token", default="testtoken", help="test token")
    p.add_argument("--startup-timeout", type=float, default=20.0, help="startup timeout seconds")
    p.add_argument(
        "--require-delivery",
        action="store_true",
        help="require delivered > 0 in push test (client must be connected)",
    )
    return p.parse_args()


def wait_health(base_url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    url = f"{base_url}/healthz"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.getcode() == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def restore_config(original_exists: bool, original_text: str | None) -> None:
    if original_exists and original_text is not None:
        CLIENT_CFG.write_text(original_text, encoding="utf-8")
    elif CLIENT_CFG.exists():
        CLIENT_CFG.unlink()


def stream_reader(prefix: str, pipe, lines: list[str]) -> None:
    try:
        for line in iter(pipe.readline, ""):
            s = line.rstrip("\n")
            lines.append(s)
            print(f"[{prefix}] {s}")
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    args = parse_args()
    base_url = f"http://127.0.0.1:{args.port}"

    original_exists = CLIENT_CFG.exists()
    original_text = CLIENT_CFG.read_text(encoding="utf-8") if original_exists else None

    relay_proc: subprocess.Popen | None = None
    client_proc: subprocess.Popen | None = None
    relay_lines: list[str] = []
    client_lines: list[str] = []

    try:
        # Force client to connect to local relay for this test run.
        temp_cfg = {
            "base": f"127.0.0.1:{args.port}",
            "room": args.room,
            "token": args.token,
            "scheme": "ws",
            "verbose": True,
        }
        CLIENT_CFG.write_text(json.dumps(temp_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] wrote temporary client config to {CLIENT_CFG}")

        relay_env = os.environ.copy()
        relay_env["PORT"] = str(args.port)
        relay_env["RELAY_TOKEN"] = args.token

        relay_proc = subprocess.Popen(
            ["node", "src/relay.js"],
            cwd=str(SERVER_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=relay_env,
        )
        relay_thread = threading.Thread(
            target=stream_reader, args=("relay", relay_proc.stdout, relay_lines), daemon=True
        )
        relay_thread.start()

        if not wait_health(base_url, args.startup_timeout):
            print("[ERROR] relay did not become healthy in time")
            return 1
        print("[INFO] relay is healthy")

        client_proc = subprocess.Popen(
            [sys.executable, str(CLIENT_SRC_DIR / "cp_client.py")],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=os.environ.copy(),
        )
        client_thread = threading.Thread(
            target=stream_reader, args=("client", client_proc.stdout, client_lines), daemon=True
        )
        client_thread.start()

        deadline = time.time() + args.startup_timeout
        connected = False
        while time.time() < deadline:
            if any("Connected" in line for line in client_lines):
                connected = True
                break
            if client_proc.poll() is not None:
                break
            time.sleep(0.2)

        if not connected:
            print("[ERROR] client did not connect in time")
            return 1
        print("[INFO] client connected")

        cmd = [
            sys.executable,
            str(ROOT / "tests" / "integration" / "test_push_api.py"),
            "--base-url",
            base_url,
            "--room",
            args.room,
            "--token",
            args.token,
        ]
        if args.require_delivery:
            cmd.append("--strict-delivered")

        print(f"[INFO] running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")

        if result.returncode != 0:
            print("[ERROR] test_push_api failed")
            return result.returncode

        print("[INFO] e2e test passed")
        return 0
    finally:
        if client_proc is not None:
            terminate_process(client_proc)
        if relay_proc is not None:
            terminate_process(relay_proc)
        restore_config(original_exists, original_text)
        print("[INFO] restored original client config")


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batch test ClipRelay POST /push API.")
    p.add_argument("--base-url", required=True, help="e.g. https://cp.sinclairl.com")
    p.add_argument("--room", required=True, help="room name")
    p.add_argument("--token", required=True, help="room/global token")
    p.add_argument("--timeout", type=float, default=10.0, help="request timeout seconds")
    p.add_argument(
        "--user-agent",
        default="curl/8.5.0",
        help="HTTP User-Agent header (some gateways block default python UA)",
    )
    p.add_argument(
        "--header",
        action="append",
        default=[],
        help='extra header in "Key: Value" format, can be used multiple times',
    )
    p.add_argument(
        "--strict-delivered",
        action="store_true",
        help="if set, require delivered > 0 (needs at least one connected ws client)",
    )
    return p.parse_args()


def build_cases() -> list[str]:
    return [
        "您正在进行短信登录，验证码931018，切勿将验证码泄露于他人，本条验证码有效期15分钟。",
        "您本次登录验证码是 4827，请勿泄露。",
        "订单号20260215，验证码654321。",
        "Your verification code is 741952. It expires in 10 minutes.",
        "Use OTP 4831 to sign in.",
        "741952 is your OTP code.",
    ]


def parse_extra_headers(raw_headers: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw_headers:
        if ":" not in item:
            continue
        k, v = item.split(":", 1)
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out


def post_push(
    base_url: str,
    room: str,
    token: str,
    text: str,
    timeout: float,
    user_agent: str,
    extra_headers: dict[str, str],
) -> tuple[int, dict | str]:
    url = f"{base_url.rstrip('/')}/push"
    payload = json.dumps({"room": room, "token": token, "text": text}, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "User-Agent": user_agent,
    }
    headers.update(extra_headers)
    req = urllib.request.Request(
        url=url,
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, raw
    except Exception as e:
        return -1, str(e)

    try:
        return code, json.loads(raw)
    except Exception:
        return code, raw


def main() -> int:
    args = parse_args()
    cases = build_cases()
    extra_headers = parse_extra_headers(args.header)

    failures = 0
    for idx, text in enumerate(cases, 1):
        code, body = post_push(
            args.base_url,
            args.room,
            args.token,
            text,
            args.timeout,
            args.user_agent,
            extra_headers,
        )
        ok = False

        if code == 200 and isinstance(body, dict) and body.get("ok") is True:
            if args.strict_delivered:
                ok = isinstance(body.get("delivered"), int) and body["delivered"] > 0
            else:
                ok = True

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] #{idx:02d} http={code} body={body!r} text={text!r}")
        if not ok:
            failures += 1

    total = len(cases)
    print(f"\nSummary: passed={total - failures}, failed={failures}, total={total}")
    if failures and isinstance(body, str) and "error code: 1010" in body:
        print(
            "\nHint: 1010 is typically from gateway/WAF, not relay.js. "
            "Try adding gateway-required headers via --header, or test with curl."
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

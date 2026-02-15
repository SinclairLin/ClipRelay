from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "client" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cp_client import extract_code  # noqa: E402


def run_cases() -> int:
    cases = [
        ("验证码931018，15分钟内有效。", "931018"),
        ("您本次登录验证码是 4827，请勿泄露。", "4827"),
        ("动态码： 000123 ，请在5分钟内使用。", "000123"),
        ("验证码：12345678，若非本人请忽略。", "12345678"),
        ("订单号20260215，验证码654321。", "654321"),
        ("您的验证码为9310189（7位）。", "9310189"),
        ("Your verification code is 741952. It expires in 10 minutes.", "741952"),
        ("Use OTP 4831 to sign in.", "4831"),
        ("Login code: 009876. Do not share it.", "009876"),
        ("Your one-time passcode is 12345678.", "12345678"),
        ("Ref: 20260215, OTP: 654321", "654321"),
        ("741952 is your OTP code.", "741952"),
        ("Security code is 123.", "Security code is 123."),
        ("No digits here.", "No digits here."),
    ]

    failed = 0
    for idx, (text, expected) in enumerate(cases, 1):
        got = extract_code(text)
        ok = got == expected
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] #{idx:02d} expected={expected!r} got={got!r} text={text!r}")
        if not ok:
            failed += 1

    total = len(cases)
    passed = total - failed
    print(f"\nSummary: passed={passed}, failed={failed}, total={total}")
    return failed


if __name__ == "__main__":
    failures = run_cases()
    raise SystemExit(1 if failures else 0)

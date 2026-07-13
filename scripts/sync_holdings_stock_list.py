#!/usr/bin/env python3
"""Build DSA STOCK_LIST from the shared Hermes holdings JSON.

Only active positions (shares > 0) are emitted. Brokerage/account details
remain local to the JSON and are not printed by this script.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    path = Path(os.environ.get("HOLDINGS_JSON", "holdings.json"))
    if not path.is_file():
        print(f"holdings file not found: {path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"invalid holdings JSON: {exc}", file=sys.stderr)
        return 2

    codes: list[str] = []
    for account in (data.get("brokerages") or {}).values():
        for code, position in (account.get("holdings") or {}).items():
            try:
                shares = float(position.get("shares", 0))
            except (TypeError, ValueError):
                shares = 0
            if shares > 0:
                code = str(code).strip().upper()
                if code and code not in codes:
                    codes.append(code)

    if not codes:
        print("no active holdings found", file=sys.stderr)
        return 3

    stock_list = ",".join(codes)
    # GitHub Actions picks this up in later steps.
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as f:
            f.write(f"STOCK_LIST={stock_list}\n")
    print(f"STOCK_LIST loaded from shared holdings: {len(codes)} active positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

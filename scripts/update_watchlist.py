#!/usr/bin/env python3
"""Update the local DSA watchlist from a live hot-list source.

Source order:
1. Eastmoney popularity ranking endpoint (股吧/人气榜 style, no MX skill required)
2. MX financial assistant query (optional)
3. Built-in cache only as an explicitly marked last resort
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(os.environ.get("DSA_HOME", Path(__file__).resolve().parents[1]))
ENV_FILE = BASE / ".env"
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
MX_SCRIPTS = [
    HERMES_HOME / "skills/miaoxiang/mx-financial-assistant/scripts/generate_answer.py",
    HERMES_HOME / "skills/finance/mx-financial-assistant/scripts/generate_answer.py",
]

FIXED_PICKS = ["603501", "002600"]
CACHE_LIST = [
    "002185", "603986", "600584", "000977", "000021", "600667", "000725", "002156",
    "600206", "002384", "002409", "000938", "601138", "002281", "002709", "000063",
    "603005", "603928", "605358", "002579", "002208", "002436", "002414", "600522",
    "000988", "002745", "001248", "002371", "600909", "002747", "002815", "603137",
    "002407", "600487", "000100", "600172", "002916", "002841",
]


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def http_json(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> object:
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET",
        headers={"User-Agent": "Mozilla/5.0", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_eastmoney_rank() -> list[str]:
    """Eastmoney current popularity ranking; does not depend on MX skills."""
    payload = json.dumps({"appId": "appId01", "sort": "desc", "pageNo": 1, "pageSize": 100}).encode()
    raw = http_json(
        "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
        data=payload,
        headers={"Content-Type": "application/json", "Referer": "https://quote.eastmoney.com/"},
    )
    if not isinstance(raw, dict) or raw.get("status") != 0 or not isinstance(raw.get("data"), list):
        raise RuntimeError(f"Eastmoney rank response invalid: {raw!r}"[:400])
    stocks: list[str] = []
    for item in raw["data"]:
        code = str(item.get("sc", ""))[-6:]
        if re.fullmatch(r"\d{6}", code) and code not in stocks:
            stocks.append(code)
    if len(stocks) < 5:
        raise RuntimeError(f"Eastmoney rank returned too few stocks: {len(stocks)}")
    return stocks


def fetch_mx_rank() -> list[str]:
    """Optional MX fallback. Missing/unsupported MX is a normal fallback case."""
    script = next((path for path in MX_SCRIPTS if path.is_file()), None)
    if script is None:
        raise RuntimeError("MX query script not installed")
    result = subprocess.run(
        [sys.executable, str(script), "--query", "今日A股热榜前100名，返回股票代码和名称完整列表", "--deep-think"],
        capture_output=True, text=True, timeout=120, cwd=str(BASE), check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"MX query exited {result.returncode}")
    payload = json.loads(result.stdout)
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("message") or payload.get("error_code") or "MX returned not ok"))
    text = json.dumps(payload, ensure_ascii=False)
    stocks = re.findall(r"(?<!\d)(?:000|001|002|003|300|600|601|603|605|688|8\d)\d{3}(?!\d)", text)
    stocks = list(dict.fromkeys(stocks))
    if len(stocks) < 5:
        raise RuntimeError(f"MX returned too few stock codes: {len(stocks)}")
    return stocks


def is_main_board(code: str) -> bool:
    return code[:3] in {"600", "601", "603", "605", "000", "001", "002", "003"}


def write_stock_list(stock_list: str) -> None:
    env = read_env()
    env["STOCK_LIST"] = stock_list
    original = ENV_FILE.read_text(encoding="utf-8", errors="replace") if ENV_FILE.exists() else ""
    comments = [line for line in original.splitlines() if line.startswith("#")]
    with ENV_FILE.open("w", encoding="utf-8") as handle:
        if comments:
            handle.write("\n".join(comments) + "\n")
        for key, value in env.items():
            if not key.startswith("#"):
                handle.write(f"{key}={value}\n")


def main() -> int:
    print("🔍 拉取实时热榜...")
    source = ""
    hot_stocks: list[str] = []
    errors: list[str] = []
    for name, fetcher in (("东方财富人气榜", fetch_eastmoney_rank), ("妙想热榜", fetch_mx_rank)):
        try:
            hot_stocks = fetcher()
            source = name
            print(f"   ✅ 来源：{source}（实时，{len(hot_stocks)} 只）")
            break
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"   ⚠️ {name}不可用：{exc}")
    if not hot_stocks:
        hot_stocks = CACHE_LIST
        source = "内置缓存（实时热榜全部失败）"
        print("   ❌ 实时热榜全部失败，最后才使用内置缓存列表")
        for error in errors:
            print(f"      - {error}")

    main_board = [code for code in hot_stocks if is_main_board(code)]
    all_stocks = list(dict.fromkeys(main_board + FIXED_PICKS))
    stock_list = ",".join(all_stocks)
    write_stock_list(stock_list)
    print(f"   主板过滤后：{len(main_board)} 只；合并固定自选后：{len(all_stocks)} 只")
    print(f"✅ STOCK_LIST 已更新，来源={source}")
    print(f"RESULT={stock_list}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

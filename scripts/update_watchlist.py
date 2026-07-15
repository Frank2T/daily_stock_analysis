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
import secrets
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


def fetch_iwencai_rank() -> list[str]:
    """Fetch iWencai's live top-100 popularity list."""
    api_key = os.environ.get("IWENCAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("IWENCAI_API_KEY is not configured")
    payload = json.dumps({
        "query": "今日A股人气排名前100名 股票代码 股票简称",
        "page": "1", "limit": "100", "is_cache": "1", "expand_index": "true",
    }, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "hithink-astock-selector",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    }
    raw = http_json("https://openapi.iwencai.com/v1/query2data", data=payload, headers=headers)
    if not isinstance(raw, dict):
        raise RuntimeError("iWencai response is not an object")
    rows = raw.get("datas") or raw.get("data") or []
    text = json.dumps(rows, ensure_ascii=False)
    stocks = re.findall(r"(?<!\d)(?:000|001|002|003|300|600|601|603|605|688|8\d)\d{3}(?!\d)", text)
    stocks = list(dict.fromkeys(stocks))
    if len(stocks) < 5:
        raise RuntimeError(f"iWencai returned too few stock codes: {len(stocks)}")
    return stocks[:100]


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
    errors: list[str] = []
    try:
        eastmoney = fetch_eastmoney_rank()[:100]
        print(f"   ✅ 东方财富人气榜：实时 {len(eastmoney)} 只")
    except Exception as exc:
        eastmoney = []
        errors.append(f"东方财富人气榜: {exc}")
        print(f"   ⚠️ 东方财富人气榜不可用：{exc}")
    try:
        iwencai = fetch_iwencai_rank()[:100]
        print(f"   ✅ 问财热榜：实时 {len(iwencai)} 只")
    except Exception as exc:
        iwencai = []
        errors.append(f"问财热榜: {exc}")
        print(f"   ⚠️ 问财热榜不可用：{exc}")

    if eastmoney and iwencai:
        iwencai_set = set(iwencai)
        intersection = [code for code in eastmoney if code in iwencai_set]
        main_board = [code for code in intersection if is_main_board(code)]
        all_stocks = main_board[:40]
        source = "东方财富∩问财（实时交集）"
        print(f"   ✅ 两榜交集：{len(intersection)} 只；主板交集：{len(main_board)} 只")
    else:
        all_stocks = [code for code in CACHE_LIST if is_main_board(code)][:40]
        source = "内置缓存（两榜至少一个实时源失败）"
        print("   ❌ 无法完成两榜交集，最后使用缓存前40只")
        for error in errors:
            print(f"      - {error}")

    stock_list = ",".join(all_stocks)
    write_stock_list(stock_list)
    print(f"   最终分析列表：{len(all_stocks)} 只（上限40）")
    print(f"✅ STOCK_LIST 已更新，来源={source}")
    print(f"RESULT={stock_list}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

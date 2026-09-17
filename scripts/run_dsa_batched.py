#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 DSA 分批执行 + 报告合并脚本
================================
背景：一次跑 40 只热榜票、3 路并发 LLM 同时调用，上游抽风会导致大量空响应/JSON 错误
（2026-08-04 实测成功率仅 47%）。本脚本把 STOCK_LIST 分批串行执行 main.py，
每批单独存报告，最后合并成完整报告。

用法：
  python3 scripts/run_dsa_batched.py [--batch-size 10] [--workers 2] [--force-run] [--keep-parts]

流程：
  1. 读取 .env 的 STOCK_LIST
  2. 按 --batch-size 切分成多批
  3. 逐批执行: main.py --stocks "batch" --no-notify --no-market-review [--workers N]
  4. 每批完成后立即把 report_YYYYMMDD.md 复制为 report_YYYYMMDD_partN.md
  5. 全部批次跑完后合并所有 part 为最终 report_YYYYMMDD.md（重新统计买卖分布）
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
REPORTS_DIR = ROOT / "reports"

# 优先使用项目 venv 的 python（系统 python3 缺 dotenv 等依赖）
VENV_PYTHON = ROOT / "venv" / "bin" / "python"
PYTHON_BIN = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def read_env() -> dict:
    env: dict = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def build_child_env() -> dict:
    """构造子进程环境：os.environ + .env 全部注入（.env 优先）。"""
    env = os.environ.copy()
    env.update(read_env())
    return env


def split_codes(stock_list: str, batch_size: int) -> list[list[str]]:
    codes = [c for c in re.split(r"[\s,;，；]+", stock_list or "") if c.strip()]
    if not codes:
        return []
    return [codes[i : i + batch_size] for i in range(0, len(codes), batch_size)]


def run_batch(batch: list[str], idx: int, args: argparse.Namespace, max_retries: int = 2) -> bool:
    date_str = datetime.now().strftime("%Y%m%d")
    codes = ",".join(batch)
    cmd = [
        PYTHON_BIN, "main.py",
        "--stocks", codes,
        "--no-notify",
        "--no-market-review",
    ]
    if args.workers:
        cmd += ["--workers", str(args.workers)]
    if args.force_run:
        cmd += ["--force-run"]

    for attempt in range(max_retries + 1):
        if attempt > 0:
            wait = 60 * attempt  # 60s, 120s backoff
            print(f"⏳ 批次 {idx} 重试 {attempt}/{max_retries}，等待 {wait}s...", flush=True)
            time.sleep(wait)

        print(f"\n=== 批次 {idx}/{args.total_batches}: {len(batch)} 只 -> {codes[:80]}... ===", flush=True)
        env = build_child_env()
        env["PYTHONPATH"] = str(ROOT)
        try:
            result = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            print(f"⏰ 批次 {idx} 超时(1800s)", flush=True)
            continue
        if result.stdout:
            print(result.stdout[-2500:], flush=True)
        if result.returncode != 0:
            print(f"⚠️ 批次 {idx} 返回码 {result.returncode}", flush=True)
            if result.stderr:
                # 检测限流关键词
                err_tail = result.stderr[-1500:]
                if any(kw in err_tail.lower() for kw in ["rate", "limit", "429", "timeout", "insufficient"]):
                    print(f"🔄 检测到限流/超时，将重试...", flush=True)
                    continue
                print(err_tail, flush=True)
            continue

        # 立即把本次报告保存为 part 文件
        src = REPORTS_DIR / f"report_{date_str}.md"
        dst = REPORTS_DIR / f"report_{date_str}_part{idx}.md"
        if src.exists() and src.stat().st_size > 0:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"✅ 批次 {idx} 报告已保存: {dst.name} ({src.stat().st_size} bytes)", flush=True)
            return True
        print(f"⚠️ 批次 {idx} 未生成报告文件，跳过保存", flush=True)
        return False

    print(f"❌ 批次 {idx} 重试{max_retries}次仍失败", flush=True)
    return False


def parse_stock_sections(content: str) -> list[str]:
    """把单批报告按 '## 股票名 (代码)' 切分成段落，去掉头部和摘要。

    只保留以 '## XXX (CODE)' 格式开头的段落（股票段落），
    丢弃 '## 📊 分析结果摘要'、'# 🎯 决策仪表盘' 等非股票段落。
    """
    lines = content.splitlines()
    sections: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current:
                sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    stock_sections = []
    for sec in sections:
        first = sec.splitlines()[0] if sec.splitlines() else ""
        # 股票段落格式: ## 股票名 (CODE)  或  ## 🔴 股票名 (CODE)
        if re.match(r"^##\s+[\u2600-\u27BF🟢🟡🟠🔴⚪]?\s*\S+\s*\(\w+\)\s*$", first):
            stock_sections.append(sec)
    return stock_sections


def merge_reports(date_str: str, args: argparse.Namespace) -> Path | None:
    parts = sorted(REPORTS_DIR.glob(f"report_{date_str}_part*.md"))
    if not parts:
        print("⚠️ 没有批次报告可合并", flush=True)
        return None

    all_sections: list[str] = []
    for part in parts:
        content = part.read_text(encoding="utf-8", errors="replace")
        sections = parse_stock_sections(content)
        all_sections.extend(sections)

    # 去重（同一只股票在多个 part 中不会出现，这里防御性去重）
    seen: set[str] = set()
    dedup: list[str] = []
    for sec in all_sections:
        m = re.match(r"^##\s+\S+\s*\((\w+)\)", sec)
        key = m.group(1) if m else sec[:40]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(sec)

    # 重新统计买卖分布
    buys = len([s for s in dedup if "🟢" in s.splitlines()[0]])
    watches = len([s for s in dedup if "🟡" in s.splitlines()[0]])
    sells = len([s for s in dedup if "🔴" in s.splitlines()[0] or "🟠" in s.splitlines()[0]])

    header = (
        f"# 🎯 {date_str[:4]}-{date_str[4:6]}-{date_str[6:]} 决策仪表盘（分批合并）\n\n"
        f"> 共分析 **{len(dedup)}** 只股票 | 🟢买入:{buys} 🟡观望:{watches} 🔴卖出:{sells}\n"
        f"市场状态：A股 · 盘后\n\n---\n\n"
    )

    final_path = REPORTS_DIR / f"report_{date_str}.md"
    final_path.write_text(header + "\n\n".join(dedup) + "\n", encoding="utf-8")
    print(f"✅ 最终报告已合并: {final_path} ({final_path.stat().st_size} bytes, {len(dedup)} 只)", flush=True)
    return final_path


def main() -> int:
    parser = argparse.ArgumentParser(description="本地 DSA 分批执行 + 报告合并")
    parser.add_argument("--batch-size", type=int, default=10, help="每批股票数（默认 10）")
    parser.add_argument("--stocks", type=str, default=None, help="自定义股票列表（逗号分隔），不传则读取 .env 的 STOCK_LIST")
    parser.add_argument("--workers", type=int, default=2, help="每批并发线程数（默认 2，降低 LLM 并发压力）")
    parser.add_argument("--force-run", action="store_true", help="跳过交易日检查")
    parser.add_argument("--keep-parts", action="store_true", help="保留 part 中间文件（默认合并后清理）")
    args = parser.parse_args()

    env = read_env()
    stock_list = args.stocks if args.stocks else env.get("STOCK_LIST", "")
    batches = split_codes(stock_list, args.batch_size)
    if not batches:
        print("❌ STOCK_LIST 为空或格式错误，请先运行 scripts/update_watchlist.py", flush=True)
        return 2

    args.total_batches = len(batches)
    date_str = datetime.now().strftime("%Y%m%d")
    print(f"📋 STOCK_LIST 共 {sum(len(b) for b in batches)} 只，切分为 {len(batches)} 批（每批 {args.batch_size} 只）", flush=True)

    ok_count = 0
    for idx, batch in enumerate(batches, start=1):
        if run_batch(batch, idx, args):
            ok_count += 1
        # 批间休息，给上游 LLM 喘息时间
        if idx < len(batches):
            print("⏳ 批间休息 90 秒...", flush=True)
            import time
            time.sleep(90)  # 批间休息90秒，避免API限流

    final_path = merge_reports(date_str, args)
    if final_path is None:
        print("❌ 报告合并失败", flush=True)
        return 1

    if not args.keep_parts:
        for part in REPORTS_DIR.glob(f"report_{date_str}_part*.md"):
            part.unlink()
        print(f"🧹 已清理 part 中间文件（共 {len(batches)} 批，成功 {ok_count} 批）", flush=True)

    print(f"\n🎉 分批执行完成：{ok_count}/{len(batches)} 批成功，最终报告 -> {final_path}", flush=True)
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

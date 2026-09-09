#!/usr/bin/env bash
# ============================================================
# run_daily_dsa.sh — 一键完成每日DSA全流程
# 1. 检查交易日
# 2. 从 holdings.json 同步持仓 → .env STOCK_LIST
# 3. 跑持仓股分析（--stocks 直传，不走 .env）
# 4. 更新热榜 + 跑热榜分析（走 .env）
# 5. 合并报告
# 用法：bash scripts/run_daily_dsa.sh
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

# --- 交易日检查 ---
DOW=$(TZ=Asia/Shanghai date +%u)
if [ "$DOW" -eq 6 ] || [ "$DOW" -eq 7 ]; then
    echo "📭 非交易日跳过（$(TZ=Asia/Shanghai date +%A)）"
    exit 0
fi

VENV_PYTHON="./venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

echo "🕐 $(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S') 开始每日DSA分析"

# --- 1. 同步持仓 ---
HOLDINGS=$(python3 -c "
import json
d = json.load(open('/root/.hermes/shared/holdings.json'))
codes = []
for acc in d.get('brokerages',{}).values():
    for code, pos in acc.get('holdings',{}).items():
        if float(pos.get('shares',0)) > 0:
            codes.append(code)
print(','.join(codes))
" 2>/dev/null || echo "")

if [ -n "$HOLDINGS" ]; then
    echo "📋 持仓股: $HOLDINGS"
    # 写入 .env（热榜脚本也需要）
    sed -i "s/^STOCK_LIST=.*/STOCK_LIST=$HOLDINGS/" .env
else
    echo "⚠️ 持仓为空，仅跑热榜"
fi

# --- 2. 持仓股分析（如有） ---
if [ -n "$HOLDINGS" ]; then
    echo ""
    echo "━━━ 第一阶段：持仓股分析 ━━━"
    $VENV_PYTHON scripts/run_dsa_batched.py --batch-size 10 --workers 2 --stocks "$HOLDINGS" --force-run || true
fi

# --- 3. 更新热榜 ---
echo ""
echo "━━━ 第二阶段：更新热榜 ━━━"
$VENV_PYTHON scripts/update_watchlist.py 2>/dev/null || echo "⚠️ 热榜更新失败，使用旧热榜"

# --- 4. 热榜分析 ---
echo ""
echo "━━━ 第三阶段：热榜分析 ━━━"
$VENV_PYTHON scripts/run_dsa_batched.py --batch-size 10 --workers 2 --force-run || true

echo ""
echo "✅ $(TZ=Asia/Shanghai date '+%H:%M:%S') DSA全流程完成"

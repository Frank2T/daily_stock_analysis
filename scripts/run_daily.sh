#!/usr/bin/env bash
# ==========================================
# daily_stock_analysis - Local Daily Runner
# 1. Update watchlist from hot rankings
# 2. Run analysis
# 3. Save reports to ~/hermes-pve/daily-reports/
# ==========================================
set -e

BASE="/root/daily_stock_analysis"
VENV="$BASE/venv"
REPORT_DIR="/root/hermes-pve/daily-reports"

# Ensure report dir
mkdir -p "$REPORT_DIR"

# Activate venv
source "$VENV/bin/activate"

cd "$BASE"

echo "=========================================="
echo "📡 Step 1: Update watchlist from hot rankings..."
python3 scripts/update_watchlist.py
echo ""

echo "=========================================="
echo "📊 Step 2: Running stock analysis..."
echo "   Stocks: $(grep STOCK_LIST .env | head -1 | cut -d= -f2 | tr ',' '\n' | wc -l) stocks"
echo ""

# Run the analysis
python3 main.py --stocks-only 2>&1 | tee "$REPORT_DIR/last_run.log"

# Copy generated reports
DATE=$(date +%Y%m%d)
if [ -f "reports/report_${DATE}.md" ]; then
    cp "reports/report_${DATE}.md" "$REPORT_DIR/"
    echo "✅ Report saved: $REPORT_DIR/report_${DATE}.md"
fi

echo ""
echo "=========================================="
echo "✅ Done! All reports in $REPORT_DIR/"
ls -la "$REPORT_DIR/" 2>/dev/null
echo "=========================================="

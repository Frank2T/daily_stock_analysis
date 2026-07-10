#!/usr/bin/env bash
# ==========================================
# daily_stock_analysis - Local Daily Runner
# 1. Update watchlist from hot rankings
# 2. Run analysis
# 3. Send report to Telegram
# ==========================================
set -e

BASE="/root/daily_stock_analysis"
VENV="$BASE/venv"
REPORT_DIR="/root/hermes-pve/daily-reports"
HERMES_ENV="/root/hermes-pve/.env"

mkdir -p "$REPORT_DIR"
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

# Run the analysis (no Telegram notification from the system itself)
python3 main.py --no-notify --no-market-review 2>&1 | tee "$REPORT_DIR/last_run.log"

# Copy report
DATE=$(date +%Y%m%d)
REPORT_FILE=""
if [ -f "reports/report_${DATE}.md" ]; then
    REPORT_FILE="reports/report_${DATE}.md"
    cp "$REPORT_FILE" "$REPORT_DIR/"
    echo "✅ Report saved: $REPORT_DIR/report_${DATE}.md"
fi

echo ""
echo "=========================================="
echo "📤 Step 3: Sending to Telegram..."

# Read Telegram credentials from Hermes env
TG_TOKEN=$(grep TELEGRAM_BOT_TOKEN "$HERMES_ENV" 2>/dev/null | cut -d= -f2)
TG_CHAT=$(grep TELEGRAM_HOME_CHANNEL "$HERMES_ENV" 2>/dev/null | cut -d= -f2)

if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ] && [ -n "$REPORT_FILE" ]; then
    # Read the report and send via Telegram Bot API
    REPORT_TEXT=$(head -3000 "$REPORT_FILE" 2>/dev/null)
    
    # Send header
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        -d "chat_id=${TG_CHAT}" \
        -d "text=📊 本地分析报告 ${DATE}&#10;━━━━━━━━━━━━━━━&#10;来源: PVE 本地部署&#10;列表: $(grep STOCK_LIST .env | head -1 | cut -d= -f2 | tr ',' '\n' | wc -l) 只待观察股" \
        -d "parse_mode=Markdown" > /dev/null 2>&1
    
    # Send report in chunks (Telegram 4096 char limit)
    if [ ${#REPORT_TEXT} -gt 3500 ]; then
        # Split into sections and send
        echo "$REPORT_TEXT" | split -l 100 - "$REPORT_DIR/tg_chunk_"
        for chunk in "$REPORT_DIR"/tg_chunk_*; do
            CHUNK_TEXT=$(cat "$chunk" | head -200)
            if [ -n "$CHUNK_TEXT" ]; then
                curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
                    -d "chat_id=${TG_CHAT}" \
                    -d "text=${CHUNK_TEXT:0:4000}" \
                    -d "parse_mode=Markdown" > /dev/null 2>&1
                sleep 1
            fi
            rm -f "$chunk"
        done
    else
        curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
            -d "chat_id=${TG_CHAT}" \
            -d "text=${REPORT_TEXT:0:4000}" \
            -d "parse_mode=Markdown" > /dev/null 2>&1
    fi
    
    echo "✅ Report sent to Telegram"
else
    echo "⚠️  Telegram credentials not found or no report generated"
fi

echo ""
echo "=========================================="
echo "✅ Done! Report: $REPORT_DIR/report_${DATE}.md"
echo "=========================================="

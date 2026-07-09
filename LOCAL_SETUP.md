# Local Deployment

在 PVE 上的本地部署，用于每日自动分析待观察列表。

## 工作流

1. 每天 UTC 08:00（北京时间 16:00）自动运行
2. 先拉取东方财富热度榜前50 → 过滤主板 → 合并固定自选股
3. 运行分析 → 输出 Markdown 报告到 `/root/hermes-pve/daily-reports/`

## 脚本说明

- `scripts/update_watchlist.py` - 自动更新待观察列表
- `scripts/run_daily.sh` - 每日分析运行入口

## 股票列表

GitHub Actions 持仓股（6只） + 本地待观察（43只=热度榜41+固定自选2）

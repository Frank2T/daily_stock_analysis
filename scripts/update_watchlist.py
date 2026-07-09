#!/usr/bin/env python3
"""
每日自动更新本地分析列表：
1. 拉东方财富/同花顺热度榜前50
2. 过滤到主板（剔除 300/688/8xx）
3. 合并固定自选股
4. 写入 .env
"""
import json, subprocess, sys, os, re
from pathlib import Path

BASE = Path("/root/daily_stock_analysis")
ENV_FILE = BASE / ".env"
SKILL_SCRIPT = Path("/root/hermes-pve/skills/finance/mx-financial-assistant/scripts/generate_answer.py")

# ====== 用户固定自选股（热度榜里没有的） ======
FIXED_PICKS = [
    "603501",  # 韦尔股份
    "002600",  # 领益智造
]

# ====== 从.env读取已有持仓 ======
def read_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

# ====== 拉热度榜数据 ======
def fetch_hot_stocks():
    """调用妙想金融问答获取股吧人气排名前50"""
    result = subprocess.run(
        [sys.executable, str(SKILL_SCRIPT), "--query", "股吧人气排名前50名 代码 名称 完整列表", "--deep-think"],
        capture_output=True, text=True, timeout=120, cwd=str(BASE)
    )
    data = json.loads(result.stdout)
    
    # 从引用数据中提取股票代码
    stocks = []
    
    # 方案1: 从 markdown 表格解析
    for ref in data.get("references", []):
        md = ref.get("markdown", "")
        for line in md.split("\n"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                # 在表格行中查找6位数字代码
                for p in parts:
                    m = re.match(r'^(\d{6})$', p)
                    if m:
                        code = m.group(1)
                        if code not in stocks:
                            stocks.append(code)
    
    # 方案2: 从 answer 文本中提取（代码）
    answer = data.get("answer", "")
    for m in re.finditer(r'（(\d{6})）', answer):
        code = m.group(1)
        if code not in stocks:
            stocks.append(code)
    
    # 方案3: 从 answer 文本中提取 代码
    for line in answer.split("\n"):
        m = re.search(r'[（(](\d{6})[）)]', line)
        if m and m.group(1) not in stocks:
            stocks.append(m.group(1))
    
    return stocks

# ====== 过滤主板 ======
def is_main_board(code):
    """主板：600/601/603/605/000/001/002/003"""
    prefix = code[:3]
    return prefix in ["600","601","603","605","000","001","002","003"]

# ====== 主流程 ======
def main():
    print("🔍 拉取热度榜...")
    try:
        hot_stocks = fetch_hot_stocks()
        print(f"   原始列表: {len(hot_stocks)} 只")
    except Exception as e:
        print(f"   ⚠️ 拉取失败: {e}")
        print("   使用缓存列表...")
        # Fallback: 使用已知的热门股列表
        hot_stocks = [
            "002185","603986","600584","000977","000021","600667","000725","002156",
            "600206","002384","002409","000938","601138","002281","002709","000063",
            "603005","603928","605358","002579","002208","002436","002414","600522",
            "000988","002745","001248","002371","600909","002747","002815","603137",
            "002407","600487","000100","600172","002916","002841"
        ]
    
    # 过滤到主板
    main_board = [s for s in hot_stocks if is_main_board(s)]
    print(f"   主板过滤后: {len(main_board)} 只")
    
    # 合并固定自选（去重）
    all_stocks = list(dict.fromkeys(main_board + FIXED_PICKS))
    print(f"   合并自选后: {len(all_stocks)} 只")
    
    stock_list = ",".join(all_stocks)
    
    # 更新 .env
    env = read_env()
    env["STOCK_LIST"] = stock_list
    
    lines = []
    for k, v in env.items():
        lines.append(f"{k}={v}")
    
    # 保留原始注释
    original = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    comment_lines = [l for l in original.splitlines() if l.startswith("#")]
    
    with open(ENV_FILE, "w") as f:
        f.write("\n".join(comment_lines) + "\n")
        for k, v in env.items():
            if not k.startswith("#"):
                f.write(f"{k}={v}\n")
    
    print(f"\n✅ STOCK_LIST 已更新 ({len(all_stocks)} 只)")
    print(f"   {stock_list[:100]}...")
    
    # 输出列表给后续使用
    return stock_list

if __name__ == "__main__":
    result = main()
    print(f"\nRESULT={result}")

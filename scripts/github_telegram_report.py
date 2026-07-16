#!/usr/bin/env python3
"""Send the generated Markdown report and a compact summary via Telegram."""
from __future__ import annotations
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def post(method: str, fields: dict[str, str], file_field: tuple[str, bytes, str] | None = None) -> None:
    boundary = "----DSAReportBoundary"
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
    if file_field:
        name, content, filename = file_field
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: text/markdown\r\n\r\n".encode())
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}",
        data=bytes(body), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"Telegram HTTP {response.status}")


def main() -> int:
    report_dir = Path("reports")
    reports = sorted(
        report_dir.glob("report_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not reports:
        print("No stock analysis report found (expected reports/report_YYYYMMDD.md)", file=sys.stderr)
        return 2
    report = reports[0]
    text = report.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = next((x.removeprefix("# ").strip() for x in lines if x.startswith("# ")), report.name)
    overview = next((x.strip().removeprefix("> ") for x in lines if x.startswith("> 共分析")), "")
    summary_start = next((i for i, x in enumerate(lines) if "分析结果摘要" in x), None)
    picks = []
    if summary_start is not None:
        for line in lines[summary_start + 1:]:
            if line.startswith("## ") or line == "---":
                break
            if line.startswith(("🟢", "⚪", "🟠", "🔴")):
                picks.append(line.replace("**", ""))
    summary = "📊 GitHub DSA 报告总结\n" + title
    if overview:
        summary += "\n" + overview
    if picks:
        summary += "\n\n重点结论：\n" + "\n".join(picks[:12])
        if len(picks) > 12:
            summary += f"\n……其余 {len(picks)-12} 只详见 Markdown 文件"
    summary += "\n\n⚠️ 仅作数据分析参考，不构成投资建议。"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram credentials are not configured", file=sys.stderr)
        return 3
    post("sendDocument", {"chat_id": chat_id, "caption": f"GitHub DSA Markdown报告：{title}"}, ("document", report.read_bytes(), report.name))
    post("sendMessage", {"chat_id": chat_id, "text": summary})
    print(f"Sent report and summary: {report}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

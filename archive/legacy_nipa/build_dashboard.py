"""nipa.db → nipa_crawler_dashboard_live.html (원본 대시보드 디자인 + 실제 데이터)

    python build_dashboard.py
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "data" / "nipa.db"
TEMPLATE = HERE / "dashboard_template.html"
OUT = HERE.parent / "nipa_crawler_dashboard_live.html"
DELAY = 0.3


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    items = [{
        "id": r["id"], "title": r["title"], "biz": r["biz"], "start": r["start_at"], "end": r["end_at"],
        "writer": r["writer"], "posted": r["posted_at"] or r["list_date"], "views": r["views"] or 0,
        "files": r["attach_count"] or 0, "url": r["url"], "first_seen": r["first_seen"],
    } for r in conn.execute("SELECT * FROM announcements ORDER BY id DESC")]
    att = conn.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM attachments").fetchone()
    by_ext = Counter(dict(conn.execute("SELECT ext, COUNT(*) FROM attachments GROUP BY ext").fetchall()))
    run = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    last_run = None
    if run:
        last_run = {k: run[k] for k in run.keys() if k != "log"}
        last_run["log"] = json.loads(run["log"] or "[]")
    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "delay": DELAY,
        "items": items,
        "attach": {"count": att[0], "bytes": att[1], "by_ext": dict(by_ext)},
        "last_run": last_run,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", r"<\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    OUT.write_text(html, encoding="utf-8")
    print(f"{OUT.name} · 공고 {len(items)}건 · 첨부 {att[0]}개 · {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()

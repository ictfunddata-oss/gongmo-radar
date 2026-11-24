"""원본 JSON 내보내기 — 공고 1건 = JSON 1개. 수집한 그대로 내보낸다."""
import json
from pathlib import Path

ANN_SQL = """
SELECT a.ann_id, o.code AS org_code, o.name AS org_name, b.code AS board_code, b.name AS board_name,
       a.post_no, a.list_no, a.title, a.biz, a.period_raw, a.start_at, a.end_at, a.site_status, a.writer,
       a.list_date, a.posted_at, a.views, a.url, a.body, a.first_seen, a.last_seen
FROM announcements a JOIN boards b ON b.board_id = a.board_id JOIN orgs o ON o.org_id = b.org_id
ORDER BY b.code, a.posted_at DESC, a.ann_id DESC
"""
ATT_SQL = """
SELECT ann_id, seq, name, ext, size_text, size_bytes, url, file_path, file_size, sha256, downloaded_at, download_error
FROM attachments ORDER BY ann_id, seq
"""


def _safe(name):
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(name))


def export_json(conn, out_dir):
    """→ {"announcements": n, "attachments": m, "dir": 경로}"""
    out = Path(out_dir)
    atts = {}
    for r in conn.execute(ATT_SQL):
        d = dict(r)
        ann_id = d.pop("ann_id")
        d["downloaded"] = bool(d["file_path"])
        atts.setdefault(ann_id, []).append(d)
    index, n, m = [], 0, 0
    for r in conn.execute(ANN_SQL):
        d = dict(r)
        d["attachments"] = atts.get(d["ann_id"], [])
        d["body_empty"] = not (d["body"] or "").strip()
        path = out / d["board_code"] / f"{_safe(d['post_no'])}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({k: d[k] for k in ("ann_id", "board_code", "post_no", "title", "posted_at", "start_at", "end_at",
                                        "site_status", "body_empty", "url")} | {"attach_count": len(d["attachments"]),
                                                                                  "file": f"{d['board_code']}/{_safe(d['post_no'])}.json"})
        n += 1
        m += len(d["attachments"])
    (out / "_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"announcements": n, "attachments": m, "dir": str(out)}

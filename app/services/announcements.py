"""화면·API 조회용 쿼리. 외부 제공 데이터에는 작성자(담당자 이름)를 넣지 않는다."""

LIST_SQL = """
SELECT a.ann_id, o.name AS org, b.name AS board, a.post_no, a.title, a.biz, a.start_at, a.end_at,
       a.posted_at, a.views, a.attach_count, a.body_len, a.url
FROM announcements a
JOIN boards b ON b.board_id = a.board_id JOIN orgs o ON o.org_id = b.org_id
"""


def list_announcements(conn, q=None, limit=50, offset=0):
    where, args = [], []
    if q:
        where.append("(a.title LIKE ? OR a.biz LIKE ?)")
        args += [f"%{q}%"] * 2
    sql = LIST_SQL + (" WHERE " + " AND ".join(where) if where else "")
    total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    rows = conn.execute(sql + " ORDER BY a.posted_at DESC, a.ann_id DESC LIMIT ? OFFSET ?", args + [limit, offset])
    return total, [dict(r) for r in rows]


def get_announcement(conn, ann_id):
    r = conn.execute(LIST_SQL + " WHERE a.ann_id = ?", (ann_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["body"] = conn.execute("SELECT body FROM announcements WHERE ann_id=?", (ann_id,)).fetchone()[0]
    d["attachments"] = [dict(x) for x in conn.execute(
        "SELECT seq, name, ext, size_text, file_path, downloaded_at, download_error FROM attachments WHERE ann_id=? ORDER BY seq",
        (ann_id,))]
    return d


def stats(conn):
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    last = conn.execute("SELECT run_id, mode, ended_at, rows, new_rows, files_saved, errors, status FROM runs "
                        "ORDER BY started_at DESC LIMIT 1").fetchone()
    return {
        "announcements": one("SELECT COUNT(*) FROM announcements"),
        "attachments": one("SELECT COUNT(*) FROM attachments"),
        "attachments_saved": one("SELECT COUNT(*) FROM attachments WHERE file_path IS NOT NULL"),
        "last_run": dict(last) if last else None,
    }

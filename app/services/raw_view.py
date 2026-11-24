"""운영 화면 '원본 데이터' — 수집한 공고 전체와 첨부에서 읽어 구조화한 결과를 보여준다."""
import json
from pathlib import Path

_cache = {"sig": None, "data": {}}
STRUCT_FILES = ("첨부_구조화_샘플19.json", "첨부_구조화_나머지128.json", "첨부_구조화_KCA10.json")


def attachment_structs(data_dir):
    """첨부를 읽어 구조화한 결과(파일) → {ann_id: dict}. 파일이 바뀌면 다시 읽는다."""
    paths = [Path(data_dir) / n for n in STRUCT_FILES]
    sig = tuple((p.name, p.stat().st_mtime) for p in paths if p.exists())
    if sig != _cache["sig"]:
        out = {}
        for p in paths:
            if p.exists():
                for x in json.loads(p.read_text(encoding="utf-8")):
                    out[x["ann_id"]] = x
        _cache.update(sig=sig, data=out)
    return _cache["data"]


def _where(q, board, body, struct_ids, struct, year):
    w, a = [], []
    if q:
        w.append("(a.title LIKE ? OR a.body LIKE ? OR a.biz LIKE ?)")
        a += [f"%{q}%"] * 3
    if board:
        w.append("b.code = ?")
        a.append(board)
    if body == "empty":
        w.append("(a.body IS NULL OR a.body = '')")
    elif body == "has":
        w.append("(a.body IS NOT NULL AND a.body <> '')")
    if year:
        w.append("substr(a.posted_at, 1, 4) = ?")
        a.append(year)
    if struct == "yes":
        w.append(f"a.ann_id IN ({','.join(str(int(i)) for i in struct_ids) or 'NULL'})")
    elif struct == "no":
        w.append(f"a.ann_id NOT IN ({','.join(str(int(i)) for i in struct_ids) or 'NULL'})")
    return (" WHERE " + " AND ".join(w)) if w else "", a


def list_raw(conn, struct_ids, q=None, board=None, body=None, struct=None, year=None, limit=30, offset=0):
    where, args = _where(q, board, body, struct_ids, struct, year)
    base = "FROM announcements a JOIN boards b ON b.board_id=a.board_id JOIN orgs o ON o.org_id=b.org_id" + where
    total = conn.execute("SELECT COUNT(*) " + base, args).fetchone()[0]
    rows = conn.execute(
        "SELECT a.ann_id, o.name AS org, b.code AS board, a.post_no, a.title, a.biz, a.posted_at, a.start_at, a.end_at, "
        "a.site_status, a.attach_count, length(a.body) AS body_len " + base + " ORDER BY a.posted_at DESC, a.ann_id DESC LIMIT ? OFFSET ?",
        args + [limit, offset]).fetchall()
    return total, [dict(r) for r in rows]


def summary(conn, struct_ids):
    """게시판별 건수·빈 본문·첨부 구조화 건수."""
    rows = conn.execute("""SELECT b.code, o.name AS org, COUNT(*) AS n, SUM(a.body IS NULL OR a.body='') AS empty,
                           MIN(a.posted_at) AS oldest, MAX(a.posted_at) AS newest
                           FROM announcements a JOIN boards b ON b.board_id=a.board_id JOIN orgs o ON o.org_id=b.org_id GROUP BY b.code ORDER BY b.code""").fetchall()
    return [dict(r) for r in rows]


def years(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT substr(posted_at,1,4) FROM announcements WHERE posted_at IS NOT NULL ORDER BY 1 DESC")]


def get_raw(conn, ann_id):
    r = conn.execute("""SELECT a.*, o.name AS org, b.code AS board_code, b.name AS board_name
                        FROM announcements a JOIN boards b ON b.board_id=a.board_id JOIN orgs o ON o.org_id=b.org_id WHERE a.ann_id=?""", (ann_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["attachments"] = [dict(x) for x in conn.execute("SELECT * FROM attachments WHERE ann_id=? ORDER BY seq", (ann_id,))]
    return d

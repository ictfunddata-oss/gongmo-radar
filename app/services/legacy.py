"""기존 NIPA 수집 DB(archive/legacy_nipa/data/nipa.db) → 새 스키마 이관.

기존 키 id(NIPA 게시물 번호)는 post_no 로, 게시판은 nipa_business 로 옮긴다.
첨부는 목록만 옮긴다(파일 미저장 — 신규 수집분부터 저장하기로 결정).
"""
import sqlite3

from ..crawler.adapters import get_adapter_class
from ..crawler.runner import ANN_COLS, ensure_board


def migrate_legacy(conn, legacy_path, board_code="nipa_business"):
    src = sqlite3.connect(legacy_path)
    src.row_factory = sqlite3.Row
    board_id = ensure_board(conn, get_adapter_class(board_code))
    if conn.execute("SELECT COUNT(*) FROM announcements WHERE board_id=?", (board_id,)).fetchone()[0]:
        raise RuntimeError("대상 게시판에 이미 공고가 있습니다. 이관은 빈 DB에서 한 번만 실행하세요.")

    id_map, n_ann, n_att, n_run = {}, 0, 0, 0
    for r in src.execute("SELECT * FROM announcements ORDER BY id"):
        cur = conn.execute(
            f"INSERT INTO announcements (board_id, post_no, {', '.join(ANN_COLS)}, first_seen, last_seen) "
            f"VALUES ({', '.join('?' * (len(ANN_COLS) + 4))})",
            [board_id, str(r["id"])] + [r[c] for c in ANN_COLS] + [r["first_seen"], r["last_seen"]])
        id_map[r["id"]] = cur.lastrowid
        n_ann += 1
    for r in src.execute("SELECT * FROM attachments"):
        conn.execute("INSERT INTO attachments (ann_id, seq, name, ext, size_text, size_bytes, url) VALUES (?,?,?,?,?,?,?)",
                     (id_map[r["ann_id"]], r["seq"], r["name"], r["ext"], r["size_text"], r["size_bytes"], r["url"]))
        n_att += 1
    for r in src.execute("SELECT * FROM runs"):
        conn.execute("INSERT OR IGNORE INTO runs (run_id, board_id, mode, started_at, ended_at, pages_total, pages_done, "
                     "rows, new_rows, updated_rows, files_saved, errors, status, log) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
                     (r["run_id"], board_id, r["mode"], r["started_at"], r["ended_at"], r["pages_total"], r["pages_done"],
                      r["rows"], r["new_rows"], r["updated_rows"], r["errors"], "정상" if not r["errors"] else "주의", r["log"]))
        n_run += 1
    conn.commit()

    src_counts = {t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("announcements", "attachments", "runs")}
    src.close()
    return {"announcements": (src_counts["announcements"], n_ann),
            "attachments": (src_counts["attachments"], n_att),
            "runs": (src_counts["runs"], n_run)}

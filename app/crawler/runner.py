"""수집 실행 — 목록 → 상세 → DB 저장 → (신규 공고) 첨부 즉시 다운로드."""
import json
import time
from datetime import datetime

from . import attachments
from .adapters import get_adapter_class
from .http import HttpClient, RunLog
from .robots import RobotsGuard
from .utils import now_iso, parse_period

ANN_COLS = ["list_no", "title", "biz", "period_raw", "start_at", "end_at", "site_status", "writer",
            "list_date", "posted_at", "views", "body", "body_len", "attach_count", "attach_bytes", "url"]


def ensure_board(conn, adapter_cls):
    """orgs·boards 에 어댑터 정보를 등록하고 board_id 를 돌려준다."""
    conn.execute("INSERT INTO orgs(code, name, kind) VALUES (?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name",
                 (adapter_cls.org_code, adapter_cls.org_name, adapter_cls.org_kind))
    org_id = conn.execute("SELECT org_id FROM orgs WHERE code=?", (adapter_cls.org_code,)).fetchone()[0]
    conn.execute("INSERT INTO boards(org_id, code, name, list_url) VALUES (?,?,?,?) "
                 "ON CONFLICT(code) DO UPDATE SET name=excluded.name, list_url=excluded.list_url",
                 (org_id, adapter_cls.code, adapter_cls.board_name, adapter_cls.list_url))
    conn.commit()
    return conn.execute("SELECT board_id FROM boards WHERE code=?", (adapter_cls.code,)).fetchone()[0]


def save_announcement(conn, board_id, adapter, row, det, now):
    """공고 1건 저장(신규 INSERT / 기존 UPDATE). 첨부 목록은 순번 기준으로 맞추되 받은 파일 정보는 유지한다."""
    data = {**row, **{k: v for k, v in det.items() if v not in (None, "") and k != "files"}}
    files = det.get("files", [])
    data["start_at"], data["end_at"] = parse_period(data.get("period_raw"))
    data["body_len"] = len(data.get("body") or "")
    data["attach_count"] = len(files)
    data["attach_bytes"] = sum(f["size_bytes"] for f in files)
    data["url"] = adapter.detail_url(row["post_no"])

    hit = conn.execute("SELECT ann_id FROM announcements WHERE board_id=? AND post_no=?",
                       (board_id, row["post_no"])).fetchone()
    if hit:
        ann_id = hit[0]
        if not data.get("period_raw"):   # 목록·본문에 기간이 없으면 이미 저장된 기간(첨부 판독으로 채운 값 등)을 지우지 않는다
            prev = conn.execute("SELECT period_raw, start_at, end_at FROM announcements WHERE ann_id=?", (ann_id,)).fetchone()
            data["period_raw"], data["start_at"], data["end_at"] = prev["period_raw"], prev["start_at"], prev["end_at"]
        conn.execute(f"UPDATE announcements SET {', '.join(c + '=?' for c in ANN_COLS)}, last_seen=? WHERE ann_id=?",
                     [data.get(c) for c in ANN_COLS] + [now, ann_id])
    else:
        cur = conn.execute(
            f"INSERT INTO announcements (board_id, post_no, {', '.join(ANN_COLS)}, first_seen, last_seen) "
            f"VALUES ({', '.join('?' * (len(ANN_COLS) + 4))})",
            [board_id, row["post_no"]] + [data.get(c) for c in ANN_COLS] + [now, now])
        ann_id = cur.lastrowid

    old = {r["seq"]: r for r in conn.execute("SELECT * FROM attachments WHERE ann_id=?", (ann_id,))}
    for f in files:
        prev = old.get(f["seq"])
        if prev and prev["name"] == f["name"]:
            conn.execute("UPDATE attachments SET ext=?, size_text=?, size_bytes=?, url=? WHERE ann_id=? AND seq=?",
                         (f["ext"], f["size_text"], f["size_bytes"], f["url"], ann_id, f["seq"]))
        else:
            conn.execute("INSERT OR REPLACE INTO attachments (ann_id, seq, name, ext, size_text, size_bytes, url) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (ann_id, f["seq"], f["name"], f["ext"], f["size_text"], f["size_bytes"], f["url"]))
    gone = set(old) - {f["seq"] for f in files}
    if gone:
        conn.executemany("DELETE FROM attachments WHERE ann_id=? AND seq=?", [(ann_id, s) for s in gone])
    return ann_id, not hit


def download_missing(conn, http, adapter, ann_id, post_no, cfg, log, only_seqs=None):
    """아직 받지 않은 첨부를 받는다(only_seqs 를 주면 그 순번만). 반드시 해당 상세 페이지를 방금 읽은 세션으로 호출할 것."""
    saved = 0
    guard = getattr(http, "robots", None)
    for att in conn.execute("SELECT * FROM attachments WHERE ann_id=? AND file_path IS NULL ORDER BY seq",
                            (ann_id,)).fetchall():
        if only_seqs is not None and att["seq"] not in only_seqs:
            continue
        if guard and att["url"] and not guard.allowed(att["url"]):
            log.emit("WARN", f"첨부 건너뜀(robots.txt) {post_no}#{att['seq']}")
            continue
        res = attachments.download(http, dict(att), adapter.code, post_no, cfg["ATTACHMENT_DIR"], cfg["ATTACH_MAX_MB"])
        conn.execute(f"UPDATE attachments SET {', '.join(k + '=?' for k in res)} WHERE ann_id=? AND seq=?",
                     list(res.values()) + [ann_id, att["seq"]])
        conn.commit()   # 다음 파일을 받는 동안 쓰기 잠금을 쥐고 있지 않게 파일마다 커밋한다
        if res.get("download_error"):
            log.emit("WARN", f"첨부 실패 {post_no}#{att['seq']} · {res['download_error']}")
        else:
            saved += 1
        http.pause()
    return saved


def crawl(conn, cfg, board_code, mode="incremental", pages=None, download=None, echo=True, start_page=1, skip_known=False):
    """mode: incremental(새 글이 없는 쪽에서 중단) | full(전체 쪽). pages 를 주면 앞 N쪽만."""
    adapter_cls = get_adapter_class(board_code)
    board_id = ensure_board(conn, adapter_cls)
    download = cfg["DOWNLOAD_ATTACHMENTS"] if download is None else download
    log = RunLog(echo=echo)
    http = HttpClient(log, delay=cfg["CRAWL_DELAY"])
    adapter = adapter_cls(http)
    known = conn.execute("SELECT COUNT(*) FROM announcements WHERE board_id=?", (board_id,)).fetchone()[0]
    mode_label = f"pages:{pages}" if pages else mode
    started = datetime.now()
    run_id = f"{board_code}-{started:%Y%m%d-%H%M%S}"
    log.emit("INFO", f"수집 시작 · {adapter_cls.org_name} {adapter_cls.board_name} · 방식 {mode_label} · 기존 {known}건 · 첨부 저장 {'예' if download else '아니오'}")

    page = last_page = start_page
    done = rows_n = new_n = upd_n = err_n = files_n = 0
    guard = http.robots = RobotsGuard(http, log, cfg.get("ROBOTS_CHECK", True))
    blocked = [u for u in (adapter.list_page_url(start_page), adapter.detail_url("1")) if not guard.allowed(u)]
    if blocked:
        log.emit("ERR", f"robots.txt가 수집을 허용하지 않거나 확인할 수 없어 이번 수집을 건너뜀 · {blocked[0]}")
        err_n += 1
    while not blocked:
        t0 = time.time()
        try:
            rows, last_page = adapter.fetch_list(page)
        except RuntimeError as e:
            log.emit("ERR", str(e))
            err_n += 1
            break
        limit = min(pages, last_page) if pages else last_page
        if page == 1 and not rows:
            log.emit("ERR", "1쪽 목록이 비어 있음 — 게시판 URL 또는 구조 변경 의심")
            err_n += 1
            break
        skipped_old = False
        if adapter.since:       # 기준일 이전 공고는 저장하지 않는다. 고정 공지는 순서 밖이라 건너뛰기만 하고 중단 근거로 쓰지 않는다
            kept = []
            for r in rows:
                if r.get("list_date") and r["list_date"] < adapter.since:
                    skipped_old = skipped_old or not adapter.is_pinned(r)
                else:
                    kept.append(r)
            rows = kept
        has_normal = any(not adapter.is_pinned(r) for r in rows)   # 고정 공지만 있는 쪽은 '새 글 없음' 판단에서 뺀다
        new_on_page = 0
        for row in rows:
            if skip_known and conn.execute("SELECT 1 FROM announcements WHERE board_id=? AND post_no=? AND body<>''", (board_id, str(row["post_no"]))).fetchone():
                rows_n += 1
                continue       # 본문까지 이미 받은 공고는 다시 읽지 않는다(재개용)
            try:
                det = adapter.fetch_detail(row["post_no"])
                ann_id, is_new = save_announcement(conn, board_id, adapter, row, det, now_iso())
                new_on_page += is_new
                new_n += is_new
                upd_n += not is_new
                rows_n += 1
                if is_new:
                    log.emit("FETCH", f"{row['post_no']} · {row['title'][:40]}")
                if download and is_new and det.get("files"):
                    conn.commit()   # 첨부를 받는 동안(수십 초) 웹의 쓰기가 막히지 않게 공고 저장을 먼저 끝낸다
                    files_n += download_missing(conn, http, adapter, ann_id, row["post_no"], cfg, log)
                conn.commit()
            except Exception as e:  # 한 건 실패로 전체를 멈추지 않는다
                conn.rollback()
                err_n += 1
                log.emit("ERR", f"{row['post_no']} · {type(e).__name__}: {e}")
            http.pause()
        done = page
        log.emit("OK", f"{page}/{limit}쪽 — 공고 {len(rows)}건 · 신규 {new_on_page}건 · {time.time() - t0:.1f}초")
        if page >= limit:
            break
        if skipped_old:
            log.emit("INFO", f"{page}쪽에서 {adapter.since} 이전 공고가 나와 수집을 마침")
            break
        if mode == "incremental" and not pages and known and new_on_page == 0 and has_normal:
            log.emit("INFO", f"{page}쪽에 새 글이 없어 수집을 마침")
            break
        page += 1

    ended = datetime.now()
    status = "오류" if err_n and not rows_n else "주의" if err_n else "정상"
    log.emit("INFO", f"수집 종료 · 공고 {rows_n}건 · 신규 {new_n}건 · 첨부 {files_n}개 · 오류 {err_n}건 · {(ended - started).seconds}초")
    conn.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (run_id, board_id, mode_label, started.isoformat(timespec="seconds"), ended.isoformat(timespec="seconds"),
                  last_page, done, rows_n, new_n, upd_n, files_n, err_n, status, json.dumps(log.lines[-300:], ensure_ascii=False)))
    conn.commit()
    return {"run_id": run_id, "rows": rows_n, "new": new_n, "updated": upd_n, "files": files_n, "errors": err_n, "status": status}


def fetch_attachments(conn, cfg, board_code, since=None, limit=None, echo=True, only=None):
    """이미 수집한 공고의 첨부를 받는다(상세 페이지를 다시 읽어 새 토큰으로 다운로드).
    only 를 주면 {공고번호: {받을 첨부 순번}} 에 있는 공고·첨부만 받는다."""
    adapter_cls = get_adapter_class(board_code)
    board_id = ensure_board(conn, adapter_cls)
    log = RunLog(echo=echo)
    http = HttpClient(log, delay=cfg["CRAWL_DELAY"])
    adapter = adapter_cls(http)
    guard = http.robots = RobotsGuard(http, log, cfg.get("ROBOTS_CHECK", True))
    if not guard.allowed(adapter.detail_url("1")):
        log.emit("ERR", "robots.txt가 수집을 허용하지 않거나 확인할 수 없어 첨부 수집을 건너뜀")
        return 0
    sql = ("SELECT DISTINCT a.ann_id, a.post_no FROM announcements a JOIN attachments t ON t.ann_id=a.ann_id "
           "WHERE a.board_id=? AND t.file_path IS NULL")
    args = [board_id]
    if only is not None:
        if not only:
            return 0
        sql += f" AND a.ann_id IN ({','.join('?' * len(only))})"
        args += list(only)
    if since:
        sql += " AND a.posted_at >= ?"
        args.append(since)
    sql += " ORDER BY a.posted_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    total = 0
    for ann in conn.execute(sql, args).fetchall():
        try:
            row = conn.execute("SELECT * FROM announcements WHERE ann_id=?", (ann["ann_id"],)).fetchone()
            det = adapter.fetch_detail(ann["post_no"])
            save_announcement(conn, board_id, adapter, {"post_no": ann["post_no"], **{k: row[k] for k in ("list_no", "site_status", "title", "list_date")}},
                              det, now_iso())
            conn.commit()   # 첨부를 받는 동안 쓰기 잠금을 쥐지 않는다
            n = download_missing(conn, http, adapter, ann["ann_id"], ann["post_no"], cfg, log,
                                 only_seqs=only[ann["ann_id"]] if only is not None else None)
            conn.commit()
            total += n
            log.emit("OK", f"{ann['post_no']} · 첨부 {n}개 저장")
        except Exception as e:
            conn.rollback()
            log.emit("ERR", f"{ann['post_no']} · {type(e).__name__}: {e}")
        http.pause()
    return total

"""관리자 통계·로그 화면용 조회 — 검색어 통계, 데이터 현황, 수집·자동 실행·운영 이력 목록."""
import json
from datetime import datetime, timedelta

from . import searches


def _since(days, now=None):
    return ((now or datetime.now()) - timedelta(days=days)).isoformat(timespec="seconds")


# ── 검색어 ──
def search_summary(conn, days, now=None):
    """최근 days일 검색 현황 → {total, distinct, zero, zero_rate, avg_results, series[{day, n, zero}]}"""
    since = _since(days, now)
    total, distinct, zero, avg = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT norm), COALESCE(SUM(CASE WHEN results=0 THEN 1 ELSE 0 END),0), COALESCE(AVG(results),0) "
        "FROM search_logs WHERE searched_at >= ?", (since,)).fetchone()
    by_day = {r["d"]: (r["n"], r["z"]) for r in conn.execute(
        "SELECT substr(searched_at,1,10) AS d, COUNT(*) AS n, SUM(CASE WHEN results=0 THEN 1 ELSE 0 END) AS z "
        "FROM search_logs WHERE searched_at >= ? GROUP BY substr(searched_at,1,10)", (since,))}
    end = (now or datetime.now()).date()
    ser = []
    for i in range(days - 1, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        n, z = by_day.get(d, (0, 0))
        ser.append({"day": d, "n": n or 0, "zero": z or 0})
    return {"total": total, "distinct": distinct, "zero": zero, "zero_rate": (zero / total) if total else 0.0,
            "avg_results": float(avg), "series": ser}


def search_terms(conn, days, banned, limit=100, only_zero=False, now=None):
    """검색어별 → [{term, count, zero, avg_results, last, banned}] 많은 순. 같은 검색어(소문자)끼리 묶고 표기는 가장 먼저 쓰인 것."""
    rows = conn.execute(
        "SELECT norm, MIN(term) AS term, COUNT(*) AS n, SUM(CASE WHEN results=0 THEN 1 ELSE 0 END) AS z, AVG(results) AS avg, MAX(searched_at) AS last "
        "FROM search_logs WHERE searched_at >= ? GROUP BY norm ORDER BY n DESC, last DESC", (_since(days, now),)).fetchall()
    out = []
    for r in rows:
        if only_zero and not r["z"]:
            continue
        out.append({"term": r["term"], "count": r["n"], "zero": r["z"] or 0, "avg_results": float(r["avg"] or 0), "last": r["last"],
                    "banned": bool(banned and banned.contains(r["term"]))})
        if len(out) >= limit:
            break
    return out


# ── 데이터 현황 ──
def coverage(conn):
    """기관별 수집 현황 → [{org, total, with_body, with_period, files, saved, text_ok}]"""
    rows = conn.execute(
        "SELECT o.name AS org, COUNT(*) AS total, "
        "SUM(CASE WHEN a.body IS NOT NULL AND length(a.body) >= 50 THEN 1 ELSE 0 END) AS with_body, "
        "SUM(CASE WHEN a.end_at IS NOT NULL AND a.end_at <> '' THEN 1 ELSE 0 END) AS with_period "
        "FROM announcements a JOIN boards b ON b.board_id = a.board_id JOIN orgs o ON o.org_id = b.org_id "
        "GROUP BY o.name ORDER BY total DESC").fetchall()
    att = {r["org"]: r for r in conn.execute(
        "SELECT o.name AS org, COUNT(*) AS files, SUM(CASE WHEN t.file_path IS NOT NULL THEN 1 ELSE 0 END) AS saved, "
        "SUM(CASE WHEN t.text_status = 'ok' THEN 1 ELSE 0 END) AS text_ok "
        "FROM attachments t JOIN announcements a ON a.ann_id = t.ann_id JOIN boards b ON b.board_id = a.board_id "
        "JOIN orgs o ON o.org_id = b.org_id GROUP BY o.name")}
    out = []
    for r in rows:
        a = att.get(r["org"])
        out.append({"org": r["org"], "total": r["total"], "with_body": r["with_body"] or 0, "with_period": r["with_period"] or 0,
                    "files": a["files"] if a else 0, "saved": (a["saved"] or 0) if a else 0, "text_ok": (a["text_ok"] or 0) if a else 0})
    return out


# ── 로그 목록 ──
LOG_TABS = [("crawl", "수집"), ("auto", "자동 실행"), ("audit", "운영 이력")]


def _loads(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def crawl_runs(conn, limit, offset, only_issue=False):
    where = " WHERE r.status <> '정상' OR r.errors > 0" if only_issue else ""
    total = conn.execute("SELECT COUNT(*) FROM runs r" + where).fetchone()[0]
    rows = []
    for r in conn.execute(
            "SELECT r.run_id, r.mode, r.started_at, r.ended_at, r.pages_done, r.pages_total, r.rows, r.new_rows, r.updated_rows, "
            "r.files_saved, r.errors, r.status, r.log, o.name AS org, b.name AS board FROM runs r "
            "LEFT JOIN boards b ON b.board_id = r.board_id LEFT JOIN orgs o ON o.org_id = b.org_id" + where +
            " ORDER BY r.started_at DESC LIMIT ? OFFSET ?", (limit, offset)):
        d = dict(r)
        d["log"] = _loads(d["log"], [])
        rows.append(d)
    return total, rows


def auto_runs(conn, limit, offset):
    total = conn.execute("SELECT COUNT(*) FROM automation_runs").fetchone()[0]
    rows = []
    for r in conn.execute("SELECT run_id, trigger, started_at, ended_at, status, summary, log FROM automation_runs "
                          "ORDER BY run_id DESC LIMIT ? OFFSET ?", (limit, offset)):
        d = dict(r)
        d["summary"] = _loads(d["summary"], {})
        d["log"] = _loads(d["log"], [])
        rows.append(d)
    return total, rows


def audit_rows(conn, limit, offset, action=None):
    where, args = (" WHERE action = ?", [action]) if action else ("", [])
    total = conn.execute("SELECT COUNT(*) FROM audit_logs" + where, args).fetchone()[0]
    rows = [dict(r) for r in conn.execute("SELECT log_id, at, actor, action, target, detail FROM audit_logs" + where +
                                          " ORDER BY log_id DESC LIMIT ? OFFSET ?", args + [limit, offset])]
    actions = [r[0] for r in conn.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action")]
    return total, rows, actions


def recent_problems(conn, days=7, now=None):
    """최근 days일 안의 수집·자동 실행 문제(상태가 정상이 아니거나 오류가 있는 것) → {crawl, auto}"""
    since = _since(days, now)
    crawl = conn.execute("SELECT COUNT(*) FROM runs WHERE started_at >= ? AND (status <> '정상' OR errors > 0)", (since,)).fetchone()[0]
    auto = conn.execute("SELECT COUNT(*) FROM automation_runs WHERE started_at >= ? AND status IN ('주의','오류')", (since,)).fetchone()[0]
    return {"crawl": crawl, "auto": auto}

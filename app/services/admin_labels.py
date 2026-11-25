"""운영 '분류·정리' 화면(/admin/labels, 부록 D.3) — 유형 라벨·표준 필드·API 사용 집계."""
from datetime import datetime

from .fields.model import FIELDS, STATUSES as FIELD_STATUSES
from .labels import CLASSES, STATUSES as LABEL_STATUSES, UNCLASSIFIED

TYPES = CLASSES + (UNCLASSIFIED,)
_ORG = "FROM announcements a JOIN boards b ON b.board_id = a.board_id JOIN orgs o ON o.org_id = b.org_id"
_TYPE = f"CASE WHEN l.class IN ({', '.join('?' * len(CLASSES))}) THEN l.class ELSE '{UNCLASSIFIED}' END"


def org_types(conn):
    """기관 × 유형 건수. → [{org, counts: {유형: n}, total}] (마지막 줄은 '합계')"""
    rows, sums = {}, {t: 0 for t in TYPES}
    for r in conn.execute(f"SELECT o.name AS org, {_TYPE} AS ty, COUNT(*) AS n {_ORG} "
                          "LEFT JOIN announcement_labels l ON l.ann_id = a.ann_id GROUP BY o.name, ty ORDER BY o.name", CLASSES):
        rows.setdefault(r["org"], {t: 0 for t in TYPES})[r["ty"]] = r["n"]
        sums[r["ty"]] += r["n"]
    out = [{"org": org, "counts": c, "total": sum(c.values())} for org, c in rows.items()]
    return out + [{"org": "합계", "counts": sums, "total": sum(sums.values())}]


def label_status(conn):
    """라벨 상태별 건수. 라벨이 없는 공고는 '라벨 없음'."""
    got = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM announcement_labels GROUP BY status")}
    none = conn.execute("SELECT COUNT(*) FROM announcements a LEFT JOIN announcement_labels l ON l.ann_id = a.ann_id "
                        "WHERE l.ann_id IS NULL").fetchone()[0]
    return [(s, got.get(s, 0)) for s in LABEL_STATUSES] + [("라벨 없음", none)]


def pending(conn, limit=200):
    """'수동 확인'·'분류 보류' 공고."""
    return [dict(r) for r in conn.execute(
        f"SELECT a.ann_id, o.name AS org, a.title, l.class, l.sub, l.status, l.reason, l.labeled_at {_ORG} "
        "JOIN announcement_labels l ON l.ann_id = a.ann_id WHERE l.status IN ('수동 확인', '분류 보류') "
        "ORDER BY l.labeled_at DESC LIMIT ?", (limit,))]


def field_status(conn):
    """기관 × 칸별 상태 건수. → [{org, field, counts: {상태: n}}] (FIELDS 순서)"""
    got = {}
    for r in conn.execute(f"SELECT o.name AS org, f.field, f.status, COUNT(*) AS n {_ORG} "
                          "JOIN announcement_fields f ON f.ann_id = a.ann_id GROUP BY o.name, f.field, f.status"):
        got.setdefault((r["org"], r["field"]), {s: 0 for s in FIELD_STATUSES})[r["status"]] = r["n"]
    orgs = sorted({k[0] for k in got})
    return [{"org": o, "field": f, "counts": got[(o, f)]} for o in orgs for f in FIELDS if (o, f) in got]


def conflicts(conn, limit=200):
    """'충돌' 칸 목록."""
    return [dict(r) for r in conn.execute(
        f"SELECT a.ann_id, o.name AS org, a.title, f.field, f.value, f.note, f.source, f.source_ref {_ORG} "
        "JOIN announcement_fields f ON f.ann_id = a.ann_id WHERE f.status = '충돌' ORDER BY f.extracted_at DESC LIMIT ?", (limit,))]


def _month(d, back):
    y, m = d.year, d.month - back
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def api_usage(conn, now=None):
    """이번 달·지난달의 단계별 호출 수·토큰·비용 합계와 대체 발생 수. → [(월, [{stage, calls, ...}])]"""
    now = now or datetime.now()
    out = []
    for month in (_month(now, 0), _month(now, 1)):
        out.append((month, [dict(r) for r in conn.execute(
                "SELECT stage, COUNT(*) AS calls, SUM(items) AS items, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
                "SUM(cache_read_tokens) AS cache_read_tokens, SUM(cache_write_tokens) AS cache_write_tokens, SUM(cost_usd) AS cost_usd, "
                "SUM(fallback) AS fallbacks, SUM(outcome != 'ok') AS failed FROM llm_calls WHERE substr(started_at, 1, 7) = ? "
                "GROUP BY stage ORDER BY stage", (month,))]))
    return out


def recent_calls(conn, limit=20):
    return [dict(r) for r in conn.execute(
        "SELECT call_id, started_at, stage, mode, model, served_model, fallback, items, input_tokens, output_tokens, cost_usd, outcome, "
        "error, ms FROM llm_calls ORDER BY call_id DESC LIMIT ?", (limit,))]

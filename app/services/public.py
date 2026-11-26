"""수요자 화면(UI 시안 안2)용 데이터 — 수집한 원본 공고를 그대로 보여 준다.

- 제목·기관·신청기간·본문 요약·첨부 목록은 사이트에서 가져온 값이다. 공고를 숨기지 않는다.
- 유형(announcement_labels, ADR-047·052)과 상세의 '공고 표준 정보'(announcement_fields, ADR-051)를 함께 담는다.
  유형 필터는 브라우저(static/public.js)가 처리한다.
- 접수 상태(마감 임박·접수 중·접수 예정·상시·마감)는 신청기간으로 계산한다.
- 작성자(담당자 이름)는 넣지 않고, 본문의 이메일·전화번호는 가린다.
"""
import re
from datetime import datetime, timedelta

from . import fields, labels
from .fields.model import FIELDS, LABELS, applies
from .mask import mask_contacts

SQL = """
SELECT a.ann_id, o.name AS org, o.code AS org_code, a.title, a.biz, a.start_at, a.end_at, a.posted_at, a.list_date, a.views,
       a.attach_count, a.body, a.body_len, a.url, l.class, l.sub
FROM announcements a
JOIN boards b ON b.board_id = a.board_id JOIN orgs o ON o.org_id = b.org_id
LEFT JOIN announcement_labels l ON l.ann_id = a.ann_id
"""

# 기관 구분 배지 색 번호(CSS .org[data-c]). 새 기관은 코드 해시로 자리를 받는다
ORG_COLOR = {"nipa": 0, "nia": 1}


def org_color(code):
    return ORG_COLOR.get(code, 2 + sum(map(ord, code or "")) % 4)


STATUS = {
    "urgent": ("마감 임박", "⏰"), "open": ("접수 중", "●"), "upcoming": ("접수 예정", "◷"),
    "always": ("상시 모집", "∞"), "ended": ("접수 마감", "■"),
}


def _dt(s, end_of_day=False):
    if not s:
        return None
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s + ("T23:59:59" if end_of_day else "T00:00:00"))
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def status(start_at, end_at, title, posted, now):
    """접수 상태 — 제목에 [접수마감]이 있으면 기간과 무관하게 마감. 기간이 없고 게시 1년이 지났으면 마감."""
    start, end = _dt(start_at), _dt(end_at, end_of_day=True)
    out = {"st": None, "dleft": None, "pct": None, "span": None}
    if re.match(r"^\s*\[?\s*접수\s*마감", title or ""):
        out["st"] = "ended"
    elif not start and not end:
        p = _dt(posted)
        out["st"] = "ended" if p and now - p > timedelta(days=365) else "always"
    elif start and now < start:
        out["st"] = "upcoming"
    elif end and now > end:
        out["st"] = "ended"
    elif not end:
        out["st"] = "always"
    else:
        out["dleft"] = (end.date() - now.date()).days
        out["st"] = "urgent" if out["dleft"] <= 7 else "open"
    if start and end and end > start:
        out["span"] = (end - start).days
        out["pct"] = round(min(100, max(0, (now - start) / (end - start) * 100)), 1)
    label, icon = STATUS[out["st"]]
    out["label"] = ("오늘 마감" if out["dleft"] == 0 else f"D-{out['dleft']}") if out["dleft"] is not None else label
    out["icon"] = icon
    return out


def is_new(posted, now, days):
    """게시일(YYYY-MM-DD…)이 오늘 포함 days일 이내이면 새 공고. 게시일이 미래이거나 없으면 아니다."""
    p = _dt(posted[:10]) if posted else None
    return bool(p and timedelta(0) <= now.replace(hour=0, minute=0, second=0, microsecond=0) - p < timedelta(days=days))


def build_item(r, now, new_days=7):
    body = r["body"] or ""
    posted = r["posted_at"] or r["list_date"]
    return {
        "id": r["ann_id"], "org": r["org"], "org_c": org_color(r["org_code"]), "title": r["title"], "biz": r["biz"] or "",
        "start": r["start_at"], "end": r["end_at"], "posted": posted, "new": is_new(posted, now, new_days),
        "views": r["views"] or 0, "files": r["attach_count"] or 0, "url": r["url"], "type": labels.public_type(r),
        "summary": mask_contacts(body)[:160] if (r["body_len"] or 0) >= 50 else "",
        **status(r["start_at"], r["end_at"], r["title"], posted, now),
    }


SOURCE_LABEL = {"site": "사이트 칸", "body": "공고 본문"}


def _source_text(f):
    """칸 출처 표시 — '사이트 칸' / '공고 본문' / '첨부: 파일명', API가 찾았으면 '· AI 발췌'."""
    s = f"첨부: {f['source_ref'] or '파일'}" if f.get("source") == "attachment" else SOURCE_LABEL.get(f.get("source"), "")
    return (s + " · AI 발췌" if s else "AI 발췌") if f.get("method") == "api" else s


def standard_fields(conn, ann_id, ty):
    """'공고 표준 정보' 다섯 줄(부록 D.2). 아직 정리하지 않은 공고(행 없음)면 []."""
    saved = {f["field"]: f for f in fields.load(conn, ann_id)}
    if not saved:
        return []
    out = []
    for name in FIELDS:
        f = dict(saved.get(name) or {"field": name, "status": "미확인" if applies(ty, name) else "해당 없음"})
        f["label"] = LABELS[ty][name]
        f["source_text"] = _source_text(f)
        out.append(f)
    return out


def public_items(conn, cfg, now=None):
    """→ (보여 줄 공고 목록, 전체 공고 수) — 수집한 공고를 모두 보여 준다."""
    now = now or datetime.now()
    items = [build_item(r, now, cfg["PUBLIC_NEW_DAYS"]) for r in conn.execute(SQL).fetchall()]
    return items, len(items)


def public_item(conn, cfg, ann_id, now=None):
    r = conn.execute(SQL + " WHERE a.ann_id = ?", (ann_id,)).fetchone()
    if r is None:
        return None
    item = build_item(r, now or datetime.now())
    item["sub"] = r["sub"] if item["type"] != labels.UNCLASSIFIED else None
    item["fields"] = standard_fields(conn, ann_id, item["type"])
    item["body"] = mask_contacts(r["body"])
    item["attachments"] = [dict(x) for x in conn.execute(
        "SELECT seq, name, ext, size_text, file_path FROM attachments WHERE ann_id=? ORDER BY seq", (ann_id,))]
    return item

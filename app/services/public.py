"""수요자 화면(UI 시안 안2)용 데이터 — 수집한 원본 공고를 그대로 보여 준다.

- 제목·기관·신청기간·본문 요약·첨부 목록 등 사이트에서 가져온 값만 쓴다. 공고를 분류하거나 숨기는 판단은 하지 않는다.
- 접수 상태(마감 임박·접수 중·접수 예정·상시·마감)는 신청기간으로 계산한다.
- 작성자(담당자 이름)는 넣지 않고, 본문의 이메일·전화번호는 가린다.
"""
import re
from datetime import datetime, timedelta

from .mask import mask_contacts
from .raw_view import attachment_structs

SQL = """
SELECT a.ann_id, o.name AS org, o.code AS org_code, a.title, a.biz, a.start_at, a.end_at, a.posted_at, a.list_date, a.views,
       a.attach_count, a.body, a.body_len, a.url
FROM announcements a
JOIN boards b ON b.board_id = a.board_id JOIN orgs o ON o.org_id = b.org_id
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
        "views": r["views"] or 0, "files": r["attach_count"] or 0, "url": r["url"],
        "summary": mask_contacts(body)[:160] if (r["body_len"] or 0) >= 50 else "",
        **status(r["start_at"], r["end_at"], r["title"], posted, now),
    }


def _structs(cfg):
    """첨부를 읽어 구조화한 결과 {ann_id: dict}. 데이터 폴더가 없거나 읽을 수 없으면 빈 값."""
    try:
        return attachment_structs(cfg["DATA_DIR"]) if cfg.get("DATA_DIR") else {}
    except (OSError, ValueError, KeyError):
        return {}


def public_items(conn, cfg, now=None):
    """→ (보여 줄 공고 목록, 전체 공고 수) — 수집한 공고를 모두 보여 준다."""
    now = now or datetime.now()
    items = [build_item(r, now, cfg["PUBLIC_NEW_DAYS"]) for r in conn.execute(SQL).fetchall()]
    structs = _structs(cfg)
    for x in items:
        x["astruct"] = x["id"] in structs   # 첨부를 읽어 구조화한 결과가 있는 공고
    return items, len(items)


def public_item(conn, cfg, ann_id, now=None):
    r = conn.execute(SQL + " WHERE a.ann_id = ?", (ann_id,)).fetchone()
    if r is None:
        return None
    item = build_item(r, now or datetime.now())
    structs = _structs(cfg)
    item["astruct"] = ann_id in structs
    item["astruct_data"] = structs.get(ann_id)
    item["body"] = mask_contacts(r["body"])
    item["attachments"] = [dict(x) for x in conn.execute(
        "SELECT seq, name, ext, size_text, file_path FROM attachments WHERE ann_id=? ORDER BY seq", (ann_id,))]
    return item

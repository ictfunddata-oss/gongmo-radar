"""공고 유형 라벨(ADR-045·047·048·052) — announcement_labels 표 읽기·쓰기.

- 공고당 한 줄. source='manual'(운영 화면에서 사람이 고친 값)은 API·CLI 가져오기가 덮어쓰지 않는다(원칙 P3).
- 화면에서 라벨이 없거나 class가 NULL(분류 보류)이면 '미분류'로 보인다.
"""
from datetime import datetime

from . import audit

CLASSES = ("공모지원사업", "입찰공고", "기타")
SUBS = {
    "공모지원사업": ("지원사업", "수행기관", "참가·교육", "변경·취소"),
    "입찰공고": ("입찰", "사전규격", "협상공모", "변경·취소"),
    "기타": ("결과", "행사·설명회", "안내", "채용", "기타"),
}
UNCLASSIFIED = "미분류"
STATUSES = ("확정", "수동 확인", "분류 보류")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def get(conn, ann_id):
    """→ dict 또는 None"""
    r = conn.execute("SELECT * FROM announcement_labels WHERE ann_id=?", (ann_id,)).fetchone()
    return dict(r) if r else None


def public_type(row):
    """라벨 행(dict·Row·None) → 화면 유형. 라벨이 없거나 class가 비었으면 '미분류'."""
    if not row:
        return UNCLASSIFIED
    cls = row["class"] if "class" in row.keys() else None
    return cls if cls in CLASSES else UNCLASSIFIED


def save_api(conn, ann_id, *, cls, sub, confidence, reason, status, prompt_version, model, request_id, input_hash):
    """API·CLI 결과를 저장한다. manual 행이 있으면 저장하지 않고 False. 커밋은 부르는 쪽이 한다."""
    if conn.execute("SELECT 1 FROM announcement_labels WHERE ann_id=? AND source='manual'", (ann_id,)).fetchone():
        return False
    conn.execute(
        "INSERT INTO announcement_labels (ann_id, class, sub, confidence, reason, status, source, prompt_version, model, request_id, "
        "input_hash, labeled_at, labeled_by) VALUES (?,?,?,?,?,?,'api',?,?,?,?,?,NULL) "
        "ON CONFLICT(ann_id) DO UPDATE SET class=excluded.class, sub=excluded.sub, confidence=excluded.confidence, reason=excluded.reason, "
        "status=excluded.status, source='api', prompt_version=excluded.prompt_version, model=excluded.model, request_id=excluded.request_id, "
        "input_hash=excluded.input_hash, labeled_at=excluded.labeled_at, labeled_by=NULL",
        (ann_id, cls, sub, confidence, reason, status, prompt_version, model, request_id, input_hash, _now()))
    return True


def set_manual(conn, ann_id, cls, sub, actor):
    """운영 화면에서 유형을 고친다. class·sub가 5.6 코드표에 없으면 ValueError. 운영 이력에 남기고 커밋한다."""
    if cls not in CLASSES or sub not in SUBS[cls]:
        raise ValueError(f"유형 값이 올바르지 않습니다: {cls}/{sub}")
    before = get(conn, ann_id)
    conn.execute(
        "INSERT INTO announcement_labels (ann_id, class, sub, confidence, reason, status, source, prompt_version, model, request_id, "
        "input_hash, labeled_at, labeled_by) VALUES (?,?,?,NULL,NULL,'확정','manual',NULL,NULL,NULL,NULL,?,?) "
        "ON CONFLICT(ann_id) DO UPDATE SET class=excluded.class, sub=excluded.sub, confidence=NULL, reason=NULL, status='확정', "
        "source='manual', prompt_version=NULL, model=NULL, request_id=NULL, input_hash=NULL, labeled_at=excluded.labeled_at, "
        "labeled_by=excluded.labeled_by",
        (ann_id, cls, sub, _now(), actor))
    prev = f"{before['class'] or UNCLASSIFIED}/{before['sub'] or '-'}" if before else UNCLASSIFIED
    audit.log(conn, actor, "유형 수정", f"공고 {ann_id}", f"{prev} → {cls}/{sub}")
    conn.commit()

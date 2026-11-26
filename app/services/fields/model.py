"""표준 필드 공통 자료형(00 5.4·5.6, ADR-051)."""
from dataclasses import dataclass, field as _field

FIELDS = ("title", "content", "qualify", "area", "period")
# 유형마다 있는 칸. 여기 없는 유형(공모지원사업·입찰공고·미분류)은 다섯 칸 모두
APPLIES = {"기타": {"title", "content"}}
STATUSES = ("확인", "미확인", "해당 없음", "충돌")
SOURCES = ("site", "body", "attachment")

# 화면 칸 이름(부록 D.2)
_DEFAULT = {"title": "공고명", "content": "공고 내용", "qualify": "지원자격", "area": "공모 지원분야", "period": "공모기간"}
LABELS = {
    "공모지원사업": _DEFAULT,
    "미분류": _DEFAULT,
    "입찰공고": {"title": "공고명", "content": "사업 개요", "qualify": "입찰참가자격", "area": "분야·계약방법", "period": "입찰서 접수기간"},
    "기타": _DEFAULT,
}


def applies(cls, field):
    """이 유형에 이 칸이 있는지."""
    return field in APPLIES.get(cls, set(FIELDS))


@dataclass
class FieldValue:
    field: str
    status: str
    value: str | None = None
    source: str | None = None
    source_ref: str | None = None
    evidence: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    note: str | None = None
    method: str = "rule"
    prompt_version: str | None = None


@dataclass
class Att:
    seq: int
    name: str
    ext: str
    text: str
    engine: str | None = None


@dataclass
class Doc:
    ann_id: int
    board: str
    cls: str | None
    sub: str | None
    title: str
    biz: str
    period_raw: str
    start_at: str | None
    end_at: str | None
    body: str
    attachments: list = _field(default_factory=list)

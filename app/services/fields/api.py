"""표준 필드 API 보완(ADR-045·051, 00 부록 B.2) — 규칙이 못 찾은 칸만 extract_v1 로 원문 인용을 받아 검사한다.

- 공모지원사업의 '미확인' 칸(content·qualify·area·period)만 보낸다. title은 보내지 않는다. 한 호출에 공고 하나.
- 모델은 원문을 인용만 한다. 인용이 그 출처 원문에 있는지(공백·마크다운 기호 무시) 앱이 검사해 통과한 칸만 '확인'으로 둔다.
- 돌려주는 칸은 모두 method='api'. 같은 input_hash로 다시 부르지 않는 판단은 fields.run 이 한다(부록 C.8).
"""
import json
import re
from pathlib import Path

from .. import attach_text, llm
from ..mask import mask_contacts
from .model import FieldValue

PROMPT_VERSION = "extract_v1"
PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
API_FIELDS = ("content", "qualify", "area", "period")
MAX_TOKENS = 4000
BODY_MAX = 8000          # 본문 글자 수
ATT_MAX = 12000          # 첨부 하나의 글자 수
TOTAL_MAX = 30000        # 보내는 원문 전체
ATT_FILES = 2
VALUE_MAX = 1500
EVIDENCE_MAX = 200


def prompt():
    """→ (시스템 프롬프트, JSON 스키마)"""
    return ((PROMPT_DIR / f"{PROMPT_VERSION}.system.md").read_text(encoding="utf-8"),
            json.loads((PROMPT_DIR / f"{PROMPT_VERSION}.schema.json").read_text(encoding="utf-8")))


def sources(doc):
    """보낼 원문 → [(source_id, 글자, source, source_ref)]. 본문(최대 8,000자) 다음 pick_files 순위 첨부 최대 2개(각 12,000자), 합계 3만 자.
    연락처는 가린다. 작성자는 넣지 않는다."""
    out, left = [], TOTAL_MAX
    body = mask_contacts((doc.body or "")[:BODY_MAX + 200]).strip()[:BODY_MAX]       # 자른 뒤 가린다(긴 글에서 정규식이 느려짐)
    if body:
        out.append(("body", body, "body", None))
        left -= len(body)
    rows = [{"seq": a.seq, "name": a.name, "ext": a.ext} for a in doc.attachments if (a.text or "").strip()]
    by = {a.seq: a for a in doc.attachments}
    for r in attach_text.pick_files(rows, ATT_FILES):
        if left <= 0:
            break
        a = by[r["seq"]]
        text = mask_contacts(a.text[:ATT_MAX + 200]).strip()[:min(ATT_MAX, left)]
        out.append((f"att:{a.seq}", text, "attachment", a.name))
        left -= len(text)
    return out


def _attr(s):
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def build_input(doc, missing):
    """API에 보낼 user 메시지(부록 B.2 입력 형식)."""
    notice = {"ann_id": doc.ann_id, "title": doc.title, "class": doc.cls, "sub": doc.sub, "biz": doc.biz,
              "missing": [f for f in missing if f in API_FIELDS]}
    parts = ["다음 공고에서 요청한 칸을 찾아 원문을 그대로 옮기세요.", f"<notice>{json.dumps(notice, ensure_ascii=False)}</notice>"]
    for sid, text, _src, ref in sources(doc):
        name = f' name="{_attr(ref)}"' if ref else ""
        parts.append(f'<source id="{sid}"{name}>{text}</source>')
    return "\n".join(parts) + "\n"


_TAG = re.compile(r"<[^>]+>")
_SKIP = re.compile(r"[\s*_#>|\x60~\-=]+")


def _norm(s):
    """인용 검사용: HTML 태그·공백·마크다운 기호를 지운다."""
    return _SKIP.sub("", _TAG.sub("", s or ""))


def quote_in(quote, text):
    q = _norm(quote)
    return bool(q) and q in _norm(text)


def _dates(quote):
    """period 인용 → (start_at, end_at). 못 읽으면 (None, None)."""
    from ...crawler.adapters.nia import extract_period
    s = extract_period(quote)
    if " ~ " in s:
        a, b = s.split(" ~ ", 1)
        return a.strip() or None, b.strip() or None
    return None, None


def _unknown(f, note=None):
    return FieldValue(field=f, status="미확인", note=note, method="api", prompt_version=PROMPT_VERSION)


def supplement(conn, cfg, doc, missing, *, run_id=None, client=None):
    """'미확인' 칸을 API로 보완한다 → {칸: FieldValue}(보낸 칸 모두, method='api').
    인용 검사를 통과한 칸만 '확인', 나머지는 '미확인'(인용 불일치·API 결과는 note에)."""
    want = [f for f in API_FIELDS if f in missing]
    if not want:
        return {}
    system, schema = prompt()
    res = llm.call_json(conn, cfg, stage="extract", system=system, user_text=build_input(doc, want), schema=schema, max_tokens=MAX_TOKENS,
                        items=1, run_id=run_id, client=client)
    if res.outcome != "ok":
        return {f: _unknown(f, f"API {res.outcome}") for f in want}
    src = {sid: (text, kind, ref) for sid, text, kind, ref in sources(doc)}
    out = {}
    for x in (res.data or {}).get("fields") or []:
        f = x.get("field") if isinstance(x, dict) else None
        if f not in want or (f in out and out[f].status == "확인"):
            continue
        quote = (x.get("quote") or "").strip()
        if x.get("status") != "확인" or not quote:
            out.setdefault(f, _unknown(f))
            continue
        s = src.get(x.get("source_id") or "")
        if s is None or not quote_in(quote, s[0]):
            out[f] = _unknown(f, "인용 불일치")
            continue
        fv = FieldValue(field=f, status="확인", value=quote[:VALUE_MAX], source=s[1], source_ref=s[2],
                        evidence=((x.get("evidence") or "").strip() or quote.splitlines()[0])[:EVIDENCE_MAX],
                        method="api", prompt_version=PROMPT_VERSION)
        if f == "period":
            fv.start_at, fv.end_at = _dates(quote)
        out[f] = fv
    return {f: out.get(f) or _unknown(f) for f in want}

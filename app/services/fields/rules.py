"""표준 필드 규칙 추출(ADR-051, 00 부록 C) — Doc 하나에서 다섯 칸을 찾는다. DB를 읽지 않는 순수 함수.

찾는 순서(부록 C.3·C.4·C.5·C.6, 핸드오프 5장)
1. 사이트 칸: 제목(앞 말머리를 뗌), 신청기간(start_at·end_at)
2. 정형 파서: KCA 첨부 '입찰개요' 표, 공고서 개요 구획(NIA 본문 '일반사항'·'입찰에 부치는 사항', 입찰공고의 '사업 개요' 등)
3. 구획 머리 파서(sections): 본문(KCA·200자 미만은 건너뜀) → 첨부(공고문 > 공모안내서 > 제안요청서·과업지시서 > 규격서)
4. 기간 파서(period): 본문 → 첨부. 사이트 값과 날짜가 다르면 '충돌'(사이트 값을 보여 주고 note에 다른 출처)
유형이 기타면 qualify·area·period는 '해당 없음'. 미분류는 공모지원사업 라벨로 찾는다.
"""
import re
from dataclasses import dataclass

from ..attach_text import FORM_WORDS
from ..mask import mask_contacts
from . import period as P
from . import sections as S
from .model import FIELDS, FieldValue, applies

VALUE_MAX = 1500
EVIDENCE_MAX = 200
BODY_MIN = 200

# 칸별 라벨(부록 C.4)
SUPPORT = {
    "content": ["사업목적", "사업개요", "사업내용", "지원내용", "추진내용", "공모개요", "모집개요",
                "추진목적", "추진배경", "행사개요"],                                   # 부록 C.4 + 덧붙인 라벨(보고서)
    "qualify": ["지원대상", "신청자격", "지원자격", "참가자격", "참여자격", "모집대상", "신청대상", "응모자격",
                "응모대상", "입주대상"],
    "area": ["지원분야", "모집분야", "공모분야", "지원유형", "과제구성", "공모과제", "모집부문", "지원부문", "응모유형"],
}
BID = {
    "content": ["사업개요", "과업내용", "과업범위", "사업내용"],
    "qualify": ["입찰참가자격", "참가자격"],
}
RX = {k: {f: S.label_re(v) for f, v in d.items()} for k, d in (("support", SUPPORT), ("bid", BID))}
# 입찰공고 분야 대체값의 계약방법 라벨(앞일수록 먼저). 추진방법·선정방법은 [공모]형 입찰 공고서에 쓰인다
_METHODS = [S.label_re([x]) for x in ("계약입찰방법", "입찰방법", "입찰방식", "계약방법", "추진방법", "선정방법")]

# 첨부 순서(부록 C.3): 공고문 > 공모안내서 > 제안요청서·과업지시서 > 규격서 > 그 밖
_TIERS = [re.compile(r"공고문|공고서|모집"), re.compile(r"안내서"), re.compile(r"제안요청|과업지시|과업내용"), re.compile(r"규격")]
# 공고가 아닌 참고 법령·지침·매뉴얼 첨부는 읽지 않는다(지침 속 '지원대상' 같은 말이 걸린다)
_NOT_NOTICE = re.compile(r"규정|지침|규칙|법률|시행령|시행규칙|매뉴얼|조례|고시|\(법\)")
_ZIP_PART = re.compile(r"^###\s+(.+?\.(?:hwpx?|pdf|docx?|xlsx?|pptx?|txt|hwt))\s*$", re.I | re.M)
_PREFIX = re.compile(r"^\s*(?:\[[^\]]{1,15}\]|\([^)]{1,15}\)|【[^】]{1,15}】)\s*")
# 말머리(biz)가 유형 표시일 뿐이면 분야 대체값으로 쓰지 않는다(NIA '입찰공고', RAPA '모집공고' 등)
_TYPE_BIZ = re.compile(r"^(?:조달)?입찰공고$|사전규격|^공모$|위탁연구|공고$|^공지|^안내")


@dataclass
class Src:
    source: str          # body / attachment
    ref: str | None      # 첨부 파일명(zip이면 'zip이름/안의 이름')
    text: str            # 정리된 글자
    sectionable: bool = True     # 구획을 찾을 글인지(200자 미만 본문은 아님)


def _cut(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _found(field, value, src, evidence, **kw):
    """찾은 칸. 첨부 원문에는 담당자 연락처가 그대로 있으므로 value·evidence의 이메일·전화번호는 가린다."""
    return FieldValue(field=field, status="확인", value=_cut(mask_contacts(value), VALUE_MAX), source=src.source, source_ref=src.ref,
                      evidence=_cut(mask_contacts(evidence), EVIDENCE_MAX), **kw)


def _missing(field, note=None):
    return FieldValue(field=field, status="미확인", note=note)


def _stem(name):
    return re.sub(r"\.[^.]*$", "", (name or "").replace("\\", "/").rsplit("/", 1)[-1]).strip().lower()


def _parts(att):
    """첨부 하나 → [(이름, 참조, 글자)]. zip 행은 '### 안의 이름' 머리로 나눈다(부록 C.7)."""
    if (att.ext or "").lower() != "zip":
        return [(att.name, att.name, att.text)]
    marks = list(_ZIP_PART.finditer(att.text or ""))
    if not marks:
        return [(att.name, att.name, att.text)]
    out = []
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(att.text)
        inner = m.group(1).strip()
        out.append((inner, f"{att.name}/{inner}", att.text[m.end():end]))
    return out


def _prep(text):
    t = S.normalize(text)
    lines = t.count("\n") + 1
    return S.split_flat(t) if len(t) / lines > 400 else t      # 줄바꿈이 거의 없는 글자(기존 추출기 결과 등)


def sources(doc):
    """찾을 글자를 순서대로: 본문, 첨부(이름 순위 → hwp가 같은 이름의 pdf보다 먼저 → 순번). 서식·참고 법령 첨부는 뺀다."""
    out = []
    kca = (doc.board or "").startswith("kca")
    if doc.body and not kca:
        out.append(Src("body", None, S.split_flat(S.normalize(doc.body)), sectionable=len(doc.body) >= BODY_MIN))
    parts = []
    for att in doc.attachments:
        for name, ref, text in _parts(att):
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if not (text or "").strip() or FORM_WORDS.search(name) or _NOT_NOTICE.search(_stem(name)):
                continue
            tier = next((k for k, rx in enumerate(_TIERS) if rx.search(name)), len(_TIERS))
            parts.append((tier, ext, _stem(name), att.seq, name, ref, text))
    hwp = {p[2] for p in parts if p[1] in ("hwp", "hwpx")}
    parts = [p for p in parts if not (p[1] == "pdf" and p[2] in hwp)]
    parts.sort(key=lambda p: (p[0], 0 if p[1] in ("hwp", "hwpx") else 1, p[3]))
    out += [Src("attachment", p[5], _prep(p[6])) for p in parts]
    return out


def _section(srcs, rx):
    for s in srcs:
        if not s.sectionable:
            continue
        sec = S.find(s.text, rx)
        if sec:
            return sec, s
    return None, None


# ── 기관별 정형 파서(부록 C.6) ──

_KCA_KEYS = {"입찰건명": "name", "공고명": "name", "계약기간": "term", "납품기한": "term", "사업예산": "budget", "사업금액": "budget",
             "접수개시일시": "start", "접수마감일시": "end", "입찰방식": "method", "계약입찰방법": "method"}


def _kca(srcs):
    """KCA 입찰공고문 '입찰개요' 표 → ({키: (칸 이름, 값, 근거 줄)}, Src) 또는 None."""
    for s in srcs:
        if s.source != "attachment":
            continue
        lines = s.text.split("\n")
        for i, ln in enumerate(lines):
            if not re.search(r"입\s*찰\s*개\s*요", ln) or len(ln) > 40:
                continue
            got = {}
            for row in lines[i:i + 30]:
                h = S.head(row)
                if row is not ln and h and h[0] <= 1 and "|" not in row:     # 다음 장('2. 입찰참가자격')
                    break
                cells = [c.strip() for c in row.split("|")] if "|" in row else []
                for k in range(len(cells) - 1):
                    name = re.sub(r"^[○◦ㅇ\s]+|[\s:：]+$", "", cells[k])
                    key = re.sub(r"\(.*?\)|\s", "", name)
                    if key in _KCA_KEYS and _KCA_KEYS[key] not in got and cells[k + 1]:
                        got[_KCA_KEYS[key]] = (name, cells[k + 1], row)
            if len(got) >= 2:
                return got, s
    return None


# 공고서 첫머리 개요(NIA '1. 일반사항'·'입찰에 부치는 사항' 등): 건명·기간·예산
_OVERVIEW_HEAD = re.compile(r"일\s*반\s*사\s*항|입\s*찰\s*에\s*부\s*치\s*는\s*사\s*항|대\s*상\s*과\s*제|입\s*찰\s*개\s*요")
# 입찰공고는 제안요청서·규격서의 '사업 개요'·'구매 개요'도 개요로 본다(건명·예산·기간이 그 아래 한 줄씩 있다)
_OVERVIEW_HEAD_BID = re.compile(_OVERVIEW_HEAD.pattern + r"|사\s*업\s*개\s*요|구\s*매\s*개\s*요|과\s*업\s*개\s*요")
_OV_KEYS = {
    "name": S.label_re(["입찰명", "입찰건명", "건명", "공모명", "사업명", "과제명", "용역명", "위탁과제명", "공고명"]),
    "term": S.label_re(["계약기간", "사업기간", "협약기간", "용역기간", "연구기간"]),
    "budget": S.label_re(["사업예산", "배정예산", "사업비", "사업금액", "추정가격", "예산"]),
}


def _ov_key(cell):
    c = re.sub(r"^[^\w(]+|[\s:：]+$", "", cell)
    for k, rx in _OV_KEYS.items():
        m = rx.match(c)
        if m and len(c) - m.end() <= 8:
            return k, re.sub(r"\s+", "", c)
    return None


def _overview(srcs, head_rx):
    """공고서 개요 구획 → (content 글자, Src, 근거 줄) 또는 None. '키 : 값' 줄, '키 | 값' 표 줄, 머리 행 + 값 행 표를 읽는다."""
    for s in srcs:
        lines = S.body_lines(s.text)
        for i, ln in enumerate(lines):
            h = S.head(ln)
            if not h or not head_rx.search(h[1][:20]) or S.is_toc(ln):
                continue
            got = {}
            rows = lines[i + 1:i + 1 + S.MAX_LINES]
            for j, row in enumerate(rows):
                h2 = S.head(row)
                if h2 and h2[0] <= h[0]:
                    break
                for k, rx in _OV_KEYS.items():
                    hit = k not in got and S.kv(row, rx)
                    if hit:
                        got[k] = (re.sub(r"\s+", "", hit[0]), hit[1])
                if "|" not in row:
                    continue
                cells = [c.strip() for c in row.split("|")]
                keys = [_ov_key(c) for c in cells]
                nxt = rows[j + 1] if j + 1 < len(rows) else ""
                nxt_cells = [c.strip() for c in nxt.split("|")] if "|" in nxt else []
                if sum(bool(k) for k in keys) >= 2 and len(nxt_cells) == len(cells):      # 머리 행 + 값 행
                    for key, v in zip(keys, nxt_cells):
                        if key and key[0] not in got and v:
                            got[key[0]] = (key[1], v)
                    continue
                for key, v in zip(keys, cells[1:]):                                      # 키 | 값
                    if key and key[0] not in got and v and not _ov_key(v):
                        got[key[0]] = (key[1], v)
            if "name" in got or "budget" in got:
                text = "\n".join(f"{got[k][0]}: {got[k][1]}" for k in ("name", "term", "budget") if k in got)
                return text, s, ln
    return None


# ── 칸별 ──

def _title(doc):
    t = doc.title or ""
    while True:
        s = _PREFIX.sub("", t, count=1)
        if s == t or not s.strip():
            break
        t = s
    return FieldValue(field="title", status="확인", value=_cut(t, VALUE_MAX), source="site", evidence=_cut(doc.title, EVIDENCE_MAX))


def _labels(srcs, field, bid):
    """입찰공고는 입찰 라벨로 먼저 찾고, 없으면 공모지원사업 라벨로 찾는다(위탁연구·[공모]형 입찰 공고서)."""
    sec, s = _section(srcs, RX["bid"][field]) if bid else (None, None)
    return (sec, s) if sec else _section(srcs, RX["support"][field])


def _content(bid, srcs, kca, overview):
    if kca:
        got, s = kca
        text = "\n".join(f"{got[k][0]}: {got[k][1]}" for k in ("name", "term", "budget") if k in got)
        if text:
            return _found("content", text, s, next(got[k][2] for k in ("name", "term", "budget") if k in got))
    if overview and bid:
        return _found("content", *overview)
    sec, s = _labels(srcs, "content", bid)
    if sec:
        return _found("content", sec.value, s, sec.head)
    if overview:
        return _found("content", *overview)
    return _missing("content")


def _qualify(bid, srcs):
    sec, s = _labels(srcs, "qualify", bid)
    return _found("qualify", sec.value, s, sec.head) if sec else _missing("qualify")


def _method(srcs):
    """본문·첨부의 '계약방법 : …' 한 줄 → (값, Src, 근거 줄). 출처 순서가 먼저, 같은 글 안에서는 라벨 순서."""
    for s in srcs:
        lines = S.body_lines(s.text)
        for rx in _METHODS:
            for ln in lines:
                hit = S.kv(ln, rx)
                if hit:
                    v = re.split(r"\s※", hit[1])[0].strip()
                    return _cut(v, 100), s, ln
    return None


def _area(doc, bid, srcs, kca):
    if not bid:
        sec, s = _section(srcs, RX["support"]["area"])
        return _found("area", sec.value, s, sec.head) if sec else _missing("area")
    # 입찰공고: 지원분야 대신 게시판 분류(biz) + 계약방법(부록 C.4)
    biz = (doc.biz or "").strip()
    biz = "" if not biz or _TYPE_BIZ.search(biz) else biz
    meth = (kca[0]["method"][1], kca[1], kca[0]["method"][2]) if kca and "method" in kca[0] else _method(srcs)
    lines = ([f"분류: {biz}"] if biz else []) + ([f"계약방법: {meth[0]}"] if meth else [])
    if not lines:
        return _missing("area", "대체값 없음")
    if meth:
        fv = _found("area", "\n".join(lines), meth[1], meth[2])
    else:
        fv = FieldValue(field="area", status="확인", value=lines[0], source="site", evidence=_cut(doc.biz, EVIDENCE_MAX))
    fv.note = "대체값"
    return fv


def _day(x):
    return (x or "")[:10] or None


def _period(doc, srcs, kca):
    found = None
    if kca and "end" in kca[0]:                       # KCA 입찰개요의 접수개시일시·접수마감일시
        got, s = kca
        stamp = {k: P.dates(got[k][1]) for k in ("start", "end") if k in got}
        if all(stamp.values()):
            at = {k: P.iso(*v[0]) for k, v in stamp.items()}
            found = (at.get("start"), at["end"], " · ".join(f"{got[k][0]} {got[k][1]}" for k in stamp), s)
    ref = next((int(x[:4]) for x in (doc.start_at, doc.end_at) if x and x[:4].isdigit()), None)
    if not found:
        for s in srcs:
            r = P.find(s.text, ref)
            if r:
                found = (*r, s)
                break
    if doc.start_at or doc.end_at:
        fv = FieldValue(field="period", status="확인", value=doc.period_raw or P.show(doc.start_at, doc.end_at), source="site",
                        evidence=_cut(doc.period_raw, EVIDENCE_MAX) or None, start_at=doc.start_at, end_at=doc.end_at)
        if found:
            pairs = [(_day(doc.start_at), _day(found[0])), (_day(doc.end_at), _day(found[1]))]
            if any(a and b and a != b for a, b in pairs):
                where = "본문" if found[3].source == "body" else f"첨부({found[3].ref})"
                fv.status = "충돌"
                fv.note = _cut(f"{where}: {found[2]}", EVIDENCE_MAX)
        return fv
    if found:
        start, end, ev, s = found
        return _found("period", P.show(start, end), s, ev, start_at=start, end_at=end)
    return _missing("period")


def extract(doc):
    """Doc → {칸: FieldValue}. 다섯 칸을 모두 돌려준다(유형상 없는 칸은 '해당 없음')."""
    bid = doc.cls == "입찰공고"
    srcs = sources(doc)
    board = doc.board or ""
    kca = _kca(srcs) if board.startswith("kca") else None
    overview = _overview(srcs, _OVERVIEW_HEAD_BID if bid else _OVERVIEW_HEAD) if bid or board.startswith("nia") else None
    out = {"title": _title(doc)}
    want = {f for f in FIELDS if applies(doc.cls, f)}
    if "content" in want:
        out["content"] = _content(bid, srcs, kca, overview)
    if "qualify" in want:
        out["qualify"] = _qualify(bid, srcs)
    if "area" in want:
        out["area"] = _area(doc, bid, srcs, kca)
    if "period" in want:
        out["period"] = _period(doc, srcs, kca)
    for f in FIELDS:
        out.setdefault(f, FieldValue(field=f, status="해당 없음"))
    return {f: out[f] for f in FIELDS}

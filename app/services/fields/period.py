"""기간 파서(00 부록 C.5) — 본문·첨부 글자에서 접수 기간을 찾는다.

먼저 기존 nia.extract_period(크롤러 파일, 고치지 않음)로 읽고, 못 읽으면 보강 파서로 읽는다.
보강 파서: 두 자리 연도(’26.), '부터 … 까지', '15시', 표 한 줄의 라벨 + 날짜 두 개, 마감일만 있는 경우.
돌려주는 start·end는 announcements.start_at과 같은 형식('2026-11-19T15:00' 또는 '2026-11-19')이다.
"""
import re
from datetime import date

from ...crawler.adapters.nia import extract_period

# 날짜 하나: (4자리 연도 | ’26 같은 두 자리 연도)? 월 일 (요일)? (시각)?
_Y = r"(?:(\d{4})\s*[.\-/년]\s*|[’'‘`´]\s?(\d{2})\s*[.\-/년]\s*)?"
_MD = r"(\d{1,2})\s*[.\-/월]\s*(\d{1,2})(?!\d)\s*[.일]?"
_WD = r"(?:\s*\(\s*[월화수목금토일]\s*\))?"
_TM = r"(?:\s*,?\s*(\d{1,2})\s*(?::\s*(\d{2})(?::\d{2})?|시(?:\s*(\d{1,2})\s*분)?))?"
DATE = _Y + _MD + _WD + _TM
_DATE_RE = re.compile(DATE)
_SEP = r"\s*(?:[~∼～〜－–-]|부터)\s*"
# 끝 날짜가 일만 있는 경우('’26.11.17(화)~19(목)'): 요일이나 '일'이 붙어야 인정
_DAY_ONLY = r"(\d{1,2})\s*(?:일|(?=\s*\(\s*[월화수목금토일]\s*\)))" + _WD + _TM
RANGE_RE = re.compile(DATE + _SEP + r"(?:" + DATE + r"|" + _DAY_ONLY + r")")

# 라벨 우선순위(작을수록 먼저): 접수·신청·모집·공모기간 > 제안서·입찰서 접수 > 공고기간
_LABELS = [
    (0, r"(?:접\s*수|신\s*청|모\s*집|공\s*모)\s*(?:기\s*간|일\s*정)|신청\s*[·ㆍ/]\s*접수"),
    (1, r"(?:제안서|입찰서|가격입찰서)\s*(?:및\s*\S+\s*)?(?:접수|제출)|접수\s*개시\s*일시"),
    (2, r"공\s*고\s*기\s*간"),
]
_LABEL_RE = [(p, re.compile(rx)) for p, rx in _LABELS]
# 라벨과 날짜 사이에 이 말이 끼면 다른 기간이다
_OTHER = re.compile(r"사업\s*기간|협약\s*기간|계약\s*기간|수행\s*기간|베타\s*기간|교육\s*기간|행사\s*기간|평가|개찰|발표")
_END_ONLY = re.compile(r"(?:접수|신청|제출|공모|모집)\s*마감\s*(?:기한|일시|일)?\s*[:：]?\s*" + DATE)
# 청렴계약 정형문(00 부록 C.3)은 기간 키워드가 걸리므로 줄째 버린다
DROP = re.compile(r"청렴계약|입찰서\s*제출\s*시\s*아래")


def _year(y4, y2, ref):
    if y4:
        return int(y4)
    if y2:
        return 2000 + int(y2)
    return ref


def _mk(y, m, d):
    try:
        return date(y, int(m), int(d))
    except (TypeError, ValueError):
        return None


def _hm(h, mi, mi2):
    if h is None:
        return None
    h, m = int(h), int(mi or mi2 or 0)
    if (h, m) == (24, 0):                                  # '24:00까지' → 그날 23:59
        return "23:59"
    return f"{h:02d}:{m:02d}" if 0 <= h <= 23 and 0 <= m < 60 else None


def iso(d, hm):
    """date + 'HH:MM' → '2026-11-19T15:00'(시각이 없으면 날짜만)."""
    return f"{d.isoformat()}T{hm}" if hm else d.isoformat()


def parse_range(s, ref_year=None):
    """문자열 안의 첫 '날짜 ~ 날짜' → (start, end) 또는 None. 끝 날짜에 연도가 없으면 시작 연도를 쓴다."""
    for m in RANGE_RE.finditer(s):
        g = m.groups()
        y1 = _year(g[0], g[1], ref_year)
        a = _mk(y1, g[2], g[3]) if y1 else None
        if not a:
            continue
        if g[9] is not None:                               # 끝 날짜에 월·일이 있음
            b = _mk(_year(g[7], g[8], a.year), g[9], g[10])
            t2 = _hm(g[11], g[12], g[13])
            if b and not (g[7] or g[8]) and b < a:         # 연도 없이 해를 넘김
                b = b.replace(year=b.year + 1)
        else:                                              # 끝 날짜가 일만 있음
            b = _mk(a.year, a.month, g[14])
            t2 = _hm(g[15], g[16], g[17])
        if not b or b < a or (b - a).days > 400:
            continue
        return iso(a, _hm(g[4], g[5], g[6])), iso(b, t2)
    return None


def dates(s, ref_year=None):
    """문자열 안의 날짜들 → [(date, 'HH:MM' 또는 None)]. 연도가 없으면 앞 날짜의 연도(없으면 ref_year)."""
    out = []
    for m in _DATE_RE.finditer(s):
        g = m.groups()
        y = _year(g[0], g[1], out[-1][0].year if out else ref_year)
        d = _mk(y, g[2], g[3]) if y else None
        if d:
            out.append((d, _hm(g[4], g[5], g[6])))
    return out


def _after_label(s, ref_year):
    """라벨 바로 뒤 글자에서 기간. 라벨과 날짜 사이는 숫자 없이 60자 이내이고 다른 기간 이름이 없어야 한다."""
    dm = _DATE_RE.search(s)
    if not dm:
        return None
    gap = s[:dm.start()]
    if len(gap) > 60 or re.search(r"\d", gap) or _OTHER.search(gap):
        return None
    return parse_range(s[dm.start():dm.start() + 120], ref_year)


def _candidates(line, ref_year):
    """한 줄에서 [(우선순위, start, end)]. 표 줄('칸 | 칸')이면 라벨 칸 다음 칸들의 날짜 두 개도 본다."""
    out = []
    for prio, rx in _LABEL_RE:
        for lm in rx.finditer(line):
            cell, _, after = line[lm.end():].partition("|")
            r = _after_label(cell, ref_year)
            if not r and after:
                rest = " ".join(c for c in after.split("|") if c.strip() and not _OTHER.search(c))[:120]
                ds = dates(rest, ref_year)
                r = parse_range(rest, ref_year)
                if not r and len(ds) >= 2 and 0 <= (ds[1][0] - ds[0][0]).days <= 400:
                    r = iso(*ds[0]), iso(*ds[1])
            if r:
                out.append((prio, *r))
    return out


def find(text, ref_year=None):
    """글자 → (start, end, 근거 줄) 또는 None. start는 None일 수 있다(마감일만 적힌 경우)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip() and not DROP.search(ln)]
    if ref_year is None:                                 # 연도 없는 날짜용: 글에 처음 나오는 온전한 날짜의 연도
        ref_year = next((d.year for ln in lines[:80] for d, _ in dates(ln) if d.year >= 2000), None)
    got = extract_period("\n".join(lines))
    if got:
        a, _, b = got.partition(" ~ ")
        start, end = a.replace(" ", "T"), b.replace(" ", "T")
        return start, end, _evidence(lines, start[:10]) or got
    best = None
    for ln in lines:
        for prio, s, e in _candidates(ln, ref_year):
            if best is None or prio < best[0]:
                best = (prio, s, e, ln)
        if best and best[0] == 0:
            break
    if best:
        return best[1], best[2], best[3]
    for ln in lines:                                     # 마감일만 있는 경우
        m = _END_ONLY.search(ln)
        if m:
            g = m.groups()
            y = _year(g[0], g[1], ref_year)
            d = _mk(y, g[2], g[3]) if y else None
            if d:
                return None, iso(d, _hm(g[4], g[5], g[6])), ln
    return None


def _evidence(lines, day):
    """extract_period가 찾은 시작일이 든 첫 줄(근거 표시용)."""
    for ln in lines:
        if any(d.isoformat() == day for d, _ in dates(ln)):
            return ln
    return None


def show(start, end):
    """value용 'YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM'(시작이 없으면 '~ 마감')."""
    f = lambda x: (x or "").replace("T", " ")   # noqa: E731
    return f"{f(start)} ~ {f(end)}" if start else f"~ {f(end)}"

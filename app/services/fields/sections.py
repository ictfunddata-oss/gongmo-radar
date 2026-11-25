"""구획 머리 파서(00 부록 C.2·C.3) — 공문서 글자를 줄로 정리하고, 라벨이 붙은 구획을 잘라 낸다.

- normalize: kordoc 출력의 강조 기호·이미지·링크를 지우고, HTML 표와 마크다운 표는 행마다 '칸 | 칸' 한 줄로 바꾼다.
- split_flat: 줄바꿈이 없는 본문(수집한 body는 공백으로 이어져 있다)을 머리 기호 앞에서 줄로 나눈다.
- find: 머리 기호 뒤 20자 안에 라벨이 오는 줄(또는 '라벨 | 값' 표 줄)을 찾아, 같은 수준 이상의 다음 머리 줄 전까지를 구획으로 돌려준다.
  목차 줄·청렴계약 정형문·별지 서식(붙임 서식 머리 아래)은 버린다.
"""
import html
import re
from dataclasses import dataclass

MAX_LINES = 40
MAX_CHARS = 1500

# 머리 기호와 수준(작을수록 높다). 공문서 항목 순서(1. → 가. → 1) …)와 개조식(□ → ○)을 한 줄로 놓았다
_ROMAN = r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.?(?=\s)|(?:VIII|VII|VI|IV|IX|III|II|I|V|X)\.(?=\s)"
_MARKS = [
    (0, r"#+"),
    (0, _ROMAN),
    (1, r"\d{1,2}\.(?!\d)"),
    (2, r"[□■◆◇◐]"),
    (3, r"[가-하]\.(?=\s)"),
    (4, r"[○◦ㅇ●❍▶▸▪]|o(?=\s)"),
    (5, r"\d{1,2}\)|\(\d{1,2}\)|[가-하]\)|\([가-하]\)|[①-⑳➊-➓❶-❿]"),
]
_HEAD_RE = [(rank, re.compile(r"^(?:" + rx + r")\s*")) for rank, rx in _MARKS]
# RAPA 공고문의 '| 2 |  | 공고 개요 |' 같은 번호 표 머리 → '1.' 수준
_NUM_ROW = re.compile(r"^\d{1,2} \| ([^|]{2,30})$")

# 목차 줄: 점선·쪽 번호로 끝나거나, 번호 머리가 한 줄에 둘 이상
_TOC_END = re.compile(r"(?:\.{3,}|…+|·{3,}|ㆍ{3,}|-{3,}|_{3,})\s*\d{1,3}\s*$|-\s*\d{1,3}\s*-\s*$|\|\s*\d{1,3}\s*$")
_TOC_NUM = re.compile(r"(?:^|\s)(?:\d{1,2}|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|[가-하])\.\s*[가-힣]")
DROP = re.compile(r"청렴계약|입찰서\s*제출\s*시\s*아래")
# 붙임 서식 머리: 여기부터 끝까지는 빈칸 서식이다
_FORM_HEAD = re.compile(r"^[\[<【(]?\s*(?:별지|별첨|붙임|첨부)\s*(?:제?\s*\d+\s*(?:호|번)?)?.{0,40}(?:서식|양식|신청서|계획서|동의서|서약서|확인서)")
_FORM_IN_HEAD = re.compile(r"별지|서식")


@dataclass
class Section:
    label: str
    head: str       # 머리 줄(근거)
    value: str      # 머리 줄의 값 부분 + 구획 본문


def _cells_row(cells):
    cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
    return " | ".join(c for c in cells if c)


def _html_table(m):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S | re.I):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S | re.I)
        cells = [re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", " ", c, flags=re.I)) for c in cells]
        row = _cells_row(cells)
        if row:
            rows.append(row)
    return "\n" + "\n".join(rows) + "\n"


def normalize(text):
    """kordoc 마크다운·HTML 표가 섞인 글자 → 평문 줄(00 부록 C.2)."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"<table[^>]*>.*?</table>", _html_table, t, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", " ", t, flags=re.I)
    t = re.sub(r"</?[a-zA-Z][^>]*>", "", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)                 # 이미지
    t = re.sub(r"\[([^\]]*)\]\((?:https?:|mailto:)[^)]*\)", r"\1", t)   # 링크 → 글자
    t = t.replace("**", "").replace("__", "")
    t = re.sub(r"\\([\\`~*_.\-#|()\[\]<>+!])", r"\1", t)        # 마크다운 이스케이프
    t = html.unescape(t)
    out = []
    for ln in t.split("\n"):
        s = ln.strip()
        if not s or re.fullmatch(r"\|?[\s:|-]*-{3,}[\s:|-]*\|?", s):      # 표 구분 줄
            continue
        if s.startswith("|"):                                   # 마크다운 표 줄 → '칸 | 칸'
            s = _cells_row(s.strip("|").split("|"))
            if not s:
                continue
        s = re.sub(r"^[-*+]\s+(?=[□■◆◇◐○◦ㅇ●❍▶▸▪※])", "", s)    # '- ○ …' 목록 기호
        s = re.sub(r"^#{1,6}\s*(?=(?:" + _ROMAN + r"|\d{1,2}[.)]|[□■◆◇◐○◦ㅇ●❍▶▸]|[가-하][.)]|\(|[①-⑳]))", "", s)
        s = re.sub(r"^#{1,6}\s*", "# ", s)
        out.append(re.sub(r"[ \t ]+", " ", s))
    return "\n".join(out)


_SPLIT = re.compile(
    r"\s+(?=[□■◆◇◐○◦●❍▶▸※★]|ㅇ\s|[①-⑳]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.?\s|[가-하]\.\s|\(\d{1,2}\)\s|\d{1,2}\)\s)"
    r"|(?<!\d\.)(?<!\d)\s+(?=\d{1,2}\.\s*[가-힣「(])")


def split_flat(text):
    """줄바꿈 없이 이어진 글(수집한 본문)을 머리 기호 앞에서 줄로 나눈다."""
    return "\n".join(_SPLIT.sub("\n", ln) for ln in (text or "").split("\n"))


def head(line):
    """머리 줄이면 (수준, 기호 뒤 글자), 아니면 None."""
    m = _NUM_ROW.match(line)
    if m:
        return 1, m.group(1)
    for rank, rx in _HEAD_RE:
        m = rx.match(line)
        if m:
            return rank, line[m.end():]
    return None


def is_toc(line):
    return bool(_TOC_END.search(line)) or len(_TOC_NUM.findall(line)) >= 2


def label_re(labels):
    """라벨 목록 → 글자 사이 공백을 허용하는 정규식('지원 대상', '지 원 대 상'도 맞는다). 긴 라벨을 먼저 본다."""
    alts = sorted({re.sub(r"\s+", "", x) for x in labels}, key=len, reverse=True)
    return re.compile("|".join(r"\s*".join(map(re.escape, a)) for a in alts))


def body_lines(text):
    """찾기용 줄 목록: 청렴계약 정형문 줄은 빼고, 붙임 서식 머리부터 끝까지는 자른다."""
    out = []
    for ln in text.split("\n"):
        if len(ln) <= 80 and _FORM_HEAD.match(ln):
            break
        if not DROP.search(ln):
            out.append(ln)
    return out


def _kv_value(t, m):
    """머리 줄의 라벨 뒤가 값이면('(라벨) 값', '라벨 : 값') 그 값, 아니면 ''."""
    rest = t[m.end():]
    k = re.match(r"\s*[)\]】]?\s*[:：|]\s*", rest)
    if k:
        return rest[k.end():].strip(" |")
    if m.start() > 0 and t[m.start() - 1] in "([【" and re.match(r"\s*[)\]】]", rest):
        return re.sub(r"^\s*[)\]】]\s*[:：]?\s*", "", rest).strip(" |")
    return ""


def _label_at(t, rx):
    """머리 글자 t에서 앞 20자 안에 오는 라벨. 문장 속(쉼표 뒤, 닫히지 않은 괄호 안)에 든 라벨은 머리로 보지 않는다."""
    for m in rx.finditer(t):
        if m.start() > 20:
            return None
        pre = t[:m.start()]
        if "," in pre or "，" in pre:
            continue
        if pre.count("(") > pre.count(")") and not re.fullmatch(r".{0,5}[(\[【]\s*", pre):
            continue
        return m
    return None


def kv(line, rx):
    """'라벨 : 값'·'(라벨) 값' 꼴의 한 줄(머리 기호는 있어도 없어도 됨) → (라벨, 값) 또는 None. 라벨은 줄 앞(괄호 허용)에 와야 한다."""
    h = head(line)
    t = h[1] if h else line
    m = rx.match(t, len(t) - len(t.lstrip("([【 ")))
    v = _kv_value(t, m) if m else ""
    return (m.group(0).strip(), v) if v else None


_PAGE_END = re.compile(r"\s(?:\d{1,3}|\?)$")
_CONTACT = re.compile(r"\[(?:전화번호|이메일)\]|@|\d{2,4}-\d{3,4}-\d{4}")


def _toc_block(head_line, parts):
    """머리 줄과 구획 줄 대부분이 쪽 번호로 끝나면 목차다."""
    lines = [head_line] + parts
    return len(lines) >= 3 and sum(bool(_PAGE_END.search(x) or is_toc(x)) for x in lines) >= 0.6 * len(lines)


def find(text, rx, *, max_lines=MAX_LINES, max_chars=MAX_CHARS):
    """정리된 글자(normalize·split_flat 뒤)에서 라벨 rx가 붙은 첫 구획 → Section 또는 None."""
    lines = body_lines(text)
    for i, ln in enumerate(lines):
        h = head(ln)
        if h:
            rank, t = h
            m = _label_at(t, rx)
            if not m or is_toc(ln) or _FORM_IN_HEAD.search(t):
                continue
            first = _kv_value(t, m)
            if not first and len(t) > 40:           # 값 구분 없이 긴 줄은 머리가 아니라 문장이다
                continue
            parts = [first] if first else []
            size = len(first)
            for ln2 in lines[i + 1:i + 1 + max_lines]:
                h2 = head(ln2)
                if h2 and h2[0] <= rank or is_toc(ln2) or size + len(ln2) > max_chars:
                    break
                parts.append(ln2)
                size += len(ln2) + 1
            value = "\n".join(parts).strip()
            if len(value) < 5 or _toc_block(ln, parts):     # 빈 구획, 목차
                continue
            return Section(m.group(0).strip(), ln, value)
        if "|" in ln:                               # 표 줄 '라벨 | 값'
            cells = [c.strip() for c in ln.split("|")]
            for k, c in enumerate(cells[:2]):
                key = re.sub(r"^[^\w(]+|[\s:：]+$", "", c)
                m = rx.match(key)
                if m and len(key) - m.end() <= 6:
                    value = " | ".join(x for x in cells[k + 1:] if x)
                    if len(value) >= 5 and not is_toc(ln) and not _CONTACT.search(value):
                        return Section(m.group(0).strip(), ln, value[:max_chars])
                    break
    return None

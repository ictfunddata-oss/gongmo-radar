"""한국지능정보사회진흥원(NIA) 입찰공고 — https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336

목록은 <li>마다 doBbsFView('게시판번호','게시물번호',...) 호출을 담고, 상세는 View.do 에 cbIdx·bcIdx 를 GET 으로 주면 열린다.
목록에 번호·상태·사업구분·신청기간 칸이 없어 해당 키는 비워 두고, 제목 앞 [말머리]를 사업구분(biz)으로 쓴다.
담당자 실명은 저장하지 않고 부서명만 writer 로 쓴다.
"""
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..base import BoardAdapter
from ..utils import sp

BASE = "https://www.nia.or.kr"
CB_IDX = "78336"
VIEW_RE = re.compile(r"doBbsFView\('\d+','(\d+)'")


# ── 본문에서 접수 기간 추출 ──
# NIA 게시판에는 기간 칸이 없고 기간이 본문 문장·표에 제각각으로 적혀 있다. 패턴을 위에서부터 시도해 처음 맞는 것을 쓴다.
_D = r"(?:(\d{4})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*[.일]?"
_WD = r"(?:\s*\(\s*[월화수목금토일]\s*\))?"
_T = r"(?:\s*(\d{1,2}:\d{2}))?"
_TILDE = r"\s*[~∼～－-]\s*"
_RANGE = _D + _WD + _T + r"[^0-9~∼～]{0,6}?" + _TILDE + _D + _WD + _T
_LABELS = r"(?:공고\s*기간|공모\s*일자|공모\s*기간|접수\s*기간|신청\s*기간|모집\s*기간|공개\s*기간)"
_PERIOD_PATTERNS = [
    # 제안서ㆍ가격 전자입찰서 제출 시작일시: 2026/09/29 10:00 … 제출 마감일시: 2026/10/01 10:00
    ("bid_submit", r"제출\s*시작\s*일시\s*[:：]\s*" + _D + _T + r".{0,80}?제출\s*마감\s*일시\s*[:：]\s*" + _D + _T),
    ("label_range", _LABELS + r"[^0-9]{0,90}?" + _RANGE),
    ("table_range", r"날\s*짜\s*" + _RANGE),
]


def _ymd(y, m, d, ref_year, ref_month=None):
    y = int(y) if y else ref_year
    if not y:
        return None
    try:
        from datetime import date
        return date(y, int(m), int(d))
    except ValueError:
        return None


def _fmt(dt, hm):
    return f"{dt.isoformat()} {hm}" if hm else dt.isoformat()


def extract_period(body, posted_at=None):
    """본문에서 접수 기간을 찾아 '2026-08-12 ~ 2026-09-11'(시각이 있으면 'YYYY-MM-DD HH:MM') 문자열로 돌려준다. 못 찾으면 ''."""
    text = re.sub(r"\s+", " ", body or "")
    post_year = int(posted_at[:4]) if posted_at and posted_at[:4].isdigit() else None
    for _name, rx in _PERIOD_PATTERNS:
        for m in re.finditer(rx, text):
            g = m.groups()
            if _name == "bid_submit":   # (y,m,d,t)(y,m,d,t)
                (y1, m1, d1, t1), (y2, m2, d2, t2) = g[0:4], g[4:8]
            else:                        # (y,m,d,t)(y,m,d,t) — 범위 패턴은 날짜 6개 + 시각 2개
                y1, m1, d1, t1, y2, m2, d2, t2 = g[0], g[1], g[2], g[3], g[4], g[5], g[6], g[7]
            a = _ymd(y1, m1, d1, post_year)
            if not a:
                continue
            b = _ymd(y2, m2, d2, a.year)
            if b and not y2 and b < a:                  # 끝 날짜에 연도가 없고 시작보다 앞서면 다음 해
                b = b.replace(year=b.year + 1)
            if not b or b < a or (b - a).days > 400:   # 기간으로 보기 어려운 값
                continue
            return f"{_fmt(a, t1)} ~ {_fmt(b, t2)}"
    # 끝 날짜만 있는 경우: '신청기간 : 공고일 ~ 2026.2.24.(화) 18:00', '접수마감 기한 : 2026. 7. 3.(금) 16:00'
    m = re.search(r"(?:(?:신청|접수|제출)\s*기(?:간|한)\s*[:：]\s*공고일\s*[~∼～]|접수\s*마감\s*(?:기한|일시)?\s*[:：]|공모\s*신청\s*마감\s*[:：]?)\s*" + _D + _WD + _T, text)
    if m and posted_at:
        end = _ymd(m.group(1), m.group(2), m.group(3), post_year)
        if end and end.isoformat() >= posted_at[:10]:
            return f"{posted_at[:10]} ~ {_fmt(end, m.group(4))}"
    return ""


def _date(text):
    """'2026.10.14' → '2026-10-14'"""
    m = re.search(r"(\d{4})[.\-](\d{2})[.\-](\d{2})", text or "")
    return "-".join(m.groups()) if m else None


class NiaBidAdapter(BoardAdapter):
    code = "nia_bid"
    org_code = "nia"
    org_name = "한국지능정보사회진흥원"
    board_name = "입찰공고"
    list_url = f"{BASE}/site/nia_kor/ex/bbs/List.do?cbIdx={CB_IDX}"

    def list_page_url(self, page):
        return f"{self.list_url}&{urlencode({'pageIndex': page})}"

    def detail_url(self, post_no):
        return f"{BASE}/site/nia_kor/ex/bbs/View.do?{urlencode({'cbIdx': CB_IDX, 'bcIdx': post_no, 'parentSeq': post_no})}"

    def parse_list(self, html, page):
        soup = BeautifulSoup(html, "lxml")
        nums = [int(n) for a in soup.select(".pageNation a[href]") for n in re.findall(r"pageIndex=(\d+)", a["href"])]
        last_page = max(nums + [page])
        rows = []
        for li in soup.select(".board_type01 > ul > li"):
            a = li.find("a", onclick=VIEW_RE)
            if not a:
                continue
            subject = li.select_one("span.subject")
            for junk in subject.select("em"):          # 첨부 아이콘, 'new' 표시
                junk.decompose()
            title = sp(subject.get_text(" "))
            em = [sp(e.get_text()) for e in li.select("span.src em")]
            who = [sp(e.get_text()) for e in li.select("span.writer em")]
            tag = re.match(r"\[([^\]]+)\]", title)
            rows.append({
                "post_no": VIEW_RE.search(a["onclick"]).group(1),
                "list_no": None,
                "site_status": "",
                "title": title,
                "biz": tag.group(1) if tag else "",
                "period_raw": "",
                "writer": who[1] if len(who) > 1 else "",
                "list_date": _date(em[0]) if em else None,
            })
        return rows, last_page

    def parse_detail(self, html):
        soup = BeautifulSoup(html, "lxml")
        d = {}
        em = [sp(e.get_text()) for e in soup.select(".write_area .src em")]
        who = [sp(e.get_text()) for e in soup.select(".write_area .writer em")]
        d["posted_at"] = _date(em[0]) if em else None
        views = re.sub(r"\D", "", em[1]) if len(em) > 1 else ""
        d["views"] = int(views) if views else None
        d["writer"] = who[1] if len(who) > 1 else None
        title = soup.select_one(".tit_area")
        tag = re.match(r"\[([^\]]+)\]", sp(title.get_text())) if title else None
        d["biz"] = tag.group(1) if tag else None
        con = soup.select_one(".con_area")
        d["body"] = sp(con.get_text(" ")) if con else ""
        files = []
        for i, a in enumerate(soup.select(".fileNew_area .file_nm a[href]"), 1):
            name = sp(a.get_text())
            files.append({
                "seq": i, "name": name,
                "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                "size_text": "", "size_bytes": 0,          # 이 게시판은 파일 크기를 표시하지 않는다
                "url": BASE + a["href"] if a["href"].startswith("/") else a["href"],
            })
        d["files"] = files
        d["period_raw"] = extract_period(d["body"], d["posted_at"])
        return d

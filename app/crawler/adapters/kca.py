"""한국방송통신전파진흥원(KCA) 입찰공고 — https://www.kca.kr/boardList.do?boardId=BIDDING&pageId=www49

목록은 `.listBody-row`마다 번호·분류·제목(<a data-seq>)·작성자·작성일·파일·조회 칸을 담고, 쪽 이동은 movePage 값을 GET 으로 줘도 열린다.
상세는 boardView.do 에 seq 를 주면 열리며, 제목(h4)·작성 정보(작성자·작성일·조회)·파일 목록(크기 표기 포함)·본문(.boardContents)이 있다.
게시판에 신청기간 칸이 없다. 입찰 일정은 첨부 공고문에 있으므로 본문에서 찾을 수 있을 때만 기간을 채운다.
분류(전파검사·ICT기금관리·사전규격 공개 등)를 사업구분(biz)으로 쓴다. 작성자는 '관리자' 같은 부서 표기라 그대로 저장한다.
robots.txt: '*'는 /siiru/ 만 막는다(수집 경로는 허용).
"""
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..base import BoardAdapter
from ..utils import size_to_bytes, sp
from .nia import extract_period

BASE = "https://www.kca.kr"
PAGE_ID = "www49"
BOARD_ID = "BIDDING"
_PAGING = re.compile(r"paging\(\s*\d+\s*,\s*(\d+)\s*,\s*\d+\s*\)")
_LAST = re.compile(r"전체페이지\s*:\s*([\d,]+)")


def _int(text):
    d = re.sub(r"\D", "", text or "")
    return int(d) if d else None


def _date(text):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text or "")
    return "-".join(m.groups()) if m else None


class KcaBiddingAdapter(BoardAdapter):
    code = "kca_bidding"
    org_code = "kca"
    org_name = "한국방송통신전파진흥원"
    board_name = "입찰공고"
    list_url = f"{BASE}/boardList.do?{urlencode({'boardId': BOARD_ID, 'pageId': PAGE_ID})}"

    def list_page_url(self, page):
        return f"{self.list_url}&{urlencode({'movePage': page})}"

    def detail_url(self, post_no):
        return f"{BASE}/boardView.do?{urlencode({'pageId': PAGE_ID, 'boardId': BOARD_ID, 'seq': post_no, 'movePage': 1})}"

    def parse_list(self, html, page):
        soup = BeautifulSoup(html, "lxml")
        m = _PAGING.search(html) or _LAST.search(html)
        last_page = max(int(m.group(1).replace(",", "")) if m else page, page)
        rows = []
        for row in soup.select(".siiruBoard-list-body .listBody-row"):
            a = row.select_one("p.subject a[data-seq]")
            if not a:
                continue
            text = lambda sel: sp(row.select_one(sel).get_text()) if row.select_one(sel) else ""
            rows.append({
                "post_no": a["data-seq"],
                "list_no": _int(text("p.num")),
                "site_status": "",
                "title": sp(a.get_text()),
                "biz": text("p.category"),
                "period_raw": "",
                "writer": text("p.writer"),
                "list_date": _date(text("p.date")),
            })
        return rows, last_page

    def parse_detail(self, html):
        soup = BeautifulSoup(html, "lxml")
        view = soup.select_one(".siiruBoard-view")
        d = {"biz": None, "posted_at": None, "views": None, "writer": None, "body": "", "files": []}
        if view is None:
            return {**d, "period_raw": ""}
        h4 = view.select_one("h4")
        tag = re.match(r"\[([^\]]+)\]", sp(h4.get_text())) if h4 else None
        d["biz"] = tag.group(1) if tag else None
        info = [sp(s.get_text()) for s in view.select(".boardInfo-view span")]
        for s in info:
            if s.startswith("작성자"):
                d["writer"] = s.split(":", 1)[-1].strip() or None
            elif s.startswith("작성일"):
                d["posted_at"] = _date(s)
        if len(info) >= 3 and not info[2].startswith(("작성자", "작성일")):
            d["views"] = _int(info[2])
        con = view.select_one(".boardContents")
        d["body"] = sp(con.get_text(" ")) if con else ""
        for i, li in enumerate(view.select("dl dd ul li"), 1):
            a = li.select_one("a[href]")
            if not a:
                continue
            name = sp(a.get_text())
            size = re.search(r"size:\s*([\d.,]+\s*[KMG]?B)", li.get_text(), re.I)
            href = a["href"].replace("&amp;", "&")
            d["files"].append({
                "seq": i, "name": name,
                "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                "size_text": size.group(1) if size else "", "size_bytes": size_to_bytes(size.group(1)) if size else 0,
                "url": BASE + href if href.startswith("/") else href,
            })
        d["period_raw"] = extract_period(d["body"], d["posted_at"])
        return d

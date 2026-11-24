"""한국전파진흥협회(RAPA) 공지사항 — https://www.rapa.or.kr/ft/ny/bd04/list.do

list.do 는 빈 틀이고 실제 목록은 addList.do 에 POST(pageIndex·boardCd·boardDivn)로 받는 HTML 조각이다.
상세는 view.do?boardSeq=… 를 GET 으로도 열 수 있어 화면 링크로 쓴다. 목록 맨 위의 '공지' 고정글(번호 칸이 '공지')은
날짜 순서 밖에 있다. 이 게시판에는 접수기간 칸이 없어 본문에서 찾고, 첨부는 이름만 저장한다(담당 '관리자'는 저장하지 않는다).
"""
import math
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..base import BoardAdapter
from ..utils import sp
from .nia import extract_period

BASE = "https://www.rapa.or.kr"
BOARD = "/ft/ny/bd04"
PAGE_SIZE = 10
VIEW_RE = re.compile(r"fncPageView\('(\d+)'")
FILE_RE = re.compile(r"fncFileDown\('([^']*)','([^']*)','([^']*)'")


def _date(text):
    m = re.search(r"(\d{4})[.\-](\d{2})[.\-](\d{2})", text or "")
    return "-".join(m.groups()) if m else None


class RapaNoticeAdapter(BoardAdapter):
    code = "rapa_notice"
    org_code = "rapa"
    org_name = "한국전파진흥협회"
    board_name = "공지사항"
    list_url = f"{BASE}{BOARD}/list.do"
    since = None   # 전체 수집(10/27 사용자 지시: 사이트에 있는 것 모두)

    def list_page_url(self, page):
        return f"{BASE}{BOARD}/addList.do"

    def detail_url(self, post_no):
        return f"{BASE}{BOARD}/view.do?{urlencode({'boardSeq': post_no, 'boardCd': 'bd04', 'boardDivn': 1})}"

    def fetch_list(self, page):
        r = self.http.post(self.list_page_url(page), data={
            "pageIndex": page, "boardDivn": 1, "boardCd": "bd04", "searchCondition": 0, "searchKeyword": ""})
        return self.parse_list(r.text, page)

    def is_pinned(self, row):
        return row.get("site_status") == "공지"

    def parse_list(self, html, page):
        total = re.search(r"totCnt\"\)\.text\('([\d,]*)'\)", html)
        total = int(total.group(1).replace(",", "") or 0) if total else 0
        last_page = max(math.ceil(total / PAGE_SIZE), page)
        soup = BeautifulSoup(html, "lxml")
        rows = []
        for tr in soup.select("table.board_col_type01 tbody tr"):
            m = VIEW_RE.search(tr.get("onclick", ""))
            subject = tr.select_one("td.subject")
            if not m or not subject:
                continue
            td = tr.find_all("td")
            no = sp(td[0].get_text())
            rows.append({
                "post_no": m.group(1),
                "list_no": int(no) if no.isdigit() else None,
                "site_status": "공지" if no == "공지" else "",
                "title": sp(subject.get_text()),
                "biz": (re.match(r"\[([^\]]+)\]", sp(subject.get_text())) or [None, ""])[1],
                "period_raw": "",
                "writer": "",
                "list_date": _date(td[3].get_text()) if len(td) > 3 else None,
            })
        return rows, last_page

    def fetch_detail(self, post_no):
        return self.parse_detail(self.http.get(self.detail_url(post_no)).text)

    def parse_detail(self, html):
        soup = BeautifulSoup(html, "lxml")
        d = {}
        title = soup.select_one("tr.board_row_tit strong")
        tag = re.match(r"\[([^\]]+)\]", sp(title.get_text())) if title else None
        d["biz"] = tag.group(1) if tag else None
        for th in soup.select("table.board_row_type01 th"):
            if sp(th.get_text()) == "등록일":
                d["posted_at"] = _date(th.find_next_sibling("td").get_text())
        text = soup.select_one(".text_area")
        d["body"] = sp(text.get_text(" ")) if text else ""
        files = []
        for i, a in enumerate(soup.select("a.down_file"), 1):
            name = sp(a.get_text(" "))
            m = FILE_RE.search(a.get("onclick", ""))
            files.append({
                "seq": i, "name": name,
                "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                "size_text": "", "size_bytes": 0,
                "url": f"{BASE}{m.group(1)}?{urlencode({'atchFileId': m.group(2), 'fileSn': m.group(3)})}" if m else "",
            })
        d["files"] = files
        d["period_raw"] = extract_period(d["body"], d.get("posted_at"))
        return d

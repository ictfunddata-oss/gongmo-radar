"""정보통신산업진흥원(NIPA) 사업공고 — https://www.nipa.kr/home/2-2"""
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..base import BoardAdapter
from ..utils import size_to_bytes, sp

BASE = "https://www.nipa.kr"


class NipaBusinessAdapter(BoardAdapter):
    code = "nipa_business"
    org_code = "nipa"
    org_name = "정보통신산업진흥원"
    board_name = "사업공고"
    list_url = f"{BASE}/home/2-2"

    def list_page_url(self, page):
        return f"{self.list_url}?{urlencode({'curPage': page})}"

    def detail_url(self, post_no):
        return f"{self.list_url}/{post_no}"

    def parse_list(self, html, page):
        soup = BeautifulSoup(html, "lxml")
        # 마지막 묶음(예: 31~36쪽)에서는 '마지막 페이지' 링크가 사라지므로 쪽 링크 번호의 최댓값을 쓴다
        nums = [int(n) for a in soup.select("ul.pagination a[href]")
                for n in re.findall(r"curPage=(\d+)", a["href"])]
        last_page = max(nums + [page])
        rows = []
        for tr in soup.select("table.tbgg tbody tr"):
            a = tr.select_one('a[href^="/home/2-2/"]')
            if not a:
                continue
            td = tr.find_all("td")
            period = re.search(r"신청기간\s*:\s*(.*)", sp(td[2].get_text(" ")))
            box = tr.select_one(".bluebox")
            no = sp(td[0].text)
            rows.append({
                "post_no": a["href"].rsplit("/", 1)[1],
                "list_no": int(no) if no.isdigit() else None,
                "site_status": sp(td[1].text),
                "title": sp(a.get_text()),
                "biz": sp(box.text) if box else "",
                "period_raw": period.group(1) if period else "",
                "writer": sp(td[3].text),
                "list_date": sp(td[4].text),
            })
        return rows, last_page

    def parse_detail(self, html):
        soup = BeautifulSoup(html, "lxml")
        info = soup.select_one("td.ggtbInfo")
        d = {}
        if info:
            pick = lambda sel: info.select_one(sel)  # noqa: E731
            d["biz"] = sp(pick(".gdi1 .bluebox").text) if pick(".gdi1 .bluebox") else None
            d["period_raw"] = sp(pick(".gdi2").text).replace("신청기간 :", "").strip() if pick(".gdi2") else None
            d["writer"] = sp(pick(".infoNm").text) if pick(".infoNm") else None
            d["posted_at"] = sp(pick(".infoDt").text) if pick(".infoDt") else None
            vw = pick(".infoVw")
            d["views"] = int(re.sub(r"\D", "", vw.get_text()) or 0) if vw else None
        body, files = "", []
        for tr in soup.select("table.tb05 > tbody > tr, table.tb05 > tr"):
            head = tr.find("td", class_="bg_lightgray")
            if not head:
                continue
            label, cell = sp(head.text), head.find_next_sibling("td")
            if label == "내용" and cell:
                body = sp(cell.get_text(" "))
            elif label == "첨부파일" and cell:
                for i, a in enumerate(cell.select('a[href^="/comm/getFile"]'), 1):
                    text = sp(a.get_text(" "))
                    m = re.match(r"(.*?)\s*\(파일크기:\s*([^)]*?)\s*\)?$", text)
                    name = m.group(1) if m else text
                    size_text = m.group(2) if m else ""
                    files.append({
                        "seq": i, "name": name,
                        "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                        "size_text": size_text, "size_bytes": size_to_bytes(size_text),
                        "url": BASE + a["href"],
                    })
        d["body"] = body
        d["files"] = files
        return d

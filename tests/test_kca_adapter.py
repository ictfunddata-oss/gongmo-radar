"""KCA 입찰공고 어댑터 — 저장해 둔 실제 목록·상세 HTML(tests/fixtures/kca_*.html)로 파싱을 확인한다."""
import unittest
from pathlib import Path

from app.crawler.adapters import get_adapter_class
from app.crawler.adapters.kca import KcaBiddingAdapter

FIX = Path(__file__).resolve().parent / "fixtures"


class KcaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ad = KcaBiddingAdapter(http=None)
        cls.rows, cls.last = cls.ad.parse_list((FIX / "kca_list.html").read_text(encoding="utf-8"), 1)
        cls.det = cls.ad.parse_detail((FIX / "kca_detail.html").read_text(encoding="utf-8"))

    def test_registered_with_org_and_board(self):
        self.assertIs(get_adapter_class("kca_bidding"), KcaBiddingAdapter)
        self.assertEqual((self.ad.org_code, self.ad.org_name, self.ad.board_name), ("kca", "한국방송통신전파진흥원", "입찰공고"))
        self.assertIsNone(self.ad.since)

    def test_urls(self):
        self.assertEqual(self.ad.list_page_url(3), "https://www.kca.kr/boardList.do?boardId=BIDDING&pageId=www49&movePage=3")
        self.assertEqual(self.ad.detail_url("6239644"),
                         "https://www.kca.kr/boardView.do?pageId=www49&boardId=BIDDING&seq=6239644&movePage=1")

    def test_list_rows_and_last_page(self):
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(self.last, 232)
        r = self.rows[0]
        self.assertEqual((r["post_no"], r["list_no"], r["biz"], r["list_date"], r["writer"]),
                         ("4142469", 2317, "사전규격 공개", "2026-11-17", "관리자"))
        self.assertTrue(r["title"].startswith("(사전규격공개) 2027년 빛마루방송지원센터"))
        self.assertEqual(self.rows[1]["post_no"], "6239644")
        self.assertEqual(len({x["post_no"] for x in self.rows}), 10)       # 게시물 번호가 겹치지 않는다

    def test_detail_meta_body_and_files(self):
        d = self.det
        self.assertEqual((d["biz"], d["posted_at"], d["views"], d["writer"]), ("전파검사", "2026-11-09", 1813, "관리자"))
        self.assertIn("조달청", d["body"])
        self.assertEqual(len(d["files"]), 4)                                # 압축 일괄 다운로드 링크는 세지 않는다
        f = d["files"][0]
        self.assertEqual((f["seq"], f["name"], f["ext"], f["size_text"]), (1, "20261109_입찰공고문.pdf", "pdf", "274.62 KB"))
        self.assertEqual(f["size_bytes"], int(274.62 * 1024))
        self.assertTrue(f["url"].startswith("https://www.kca.kr/fileDownload.do?action=fileDown"))
        self.assertIn("fileSn=1", f["url"])
        self.assertNotIn("&amp;", f["url"])

    def test_empty_or_broken_pages_do_not_crash(self):
        self.assertEqual(self.ad.parse_list("<html></html>", 2), ([], 2))
        self.assertEqual(self.ad.parse_detail("<html></html>")["files"], [])


if __name__ == "__main__":
    unittest.main()

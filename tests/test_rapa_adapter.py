"""RAPA 공지사항 어댑터 — 목록(고정 공지·일반글)·상세·기준일(2026년) 처리."""
import unittest

from app.crawler.adapters import get_adapter_class
from app.crawler.adapters.rapa import RapaNoticeAdapter

LIST = """<script>$("#totCnt").text('1,834');</script>
<table class="board_col_type01"><tbody>
<tr data-url="" onclick="fncPageView('7621', this.getAttribute('data-url'))" class="notice">
 <td class="m_hid"> 공지 </td><td class="subject"> [모집공고] 재난방송 설치지원 </td><td class="m_hid"></td><td>2026.10.16</td><td class="m_hid">52</td></tr>
<tr data-url="" onclick="fncPageView('7617', this.getAttribute('data-url'))" >
 <td class="m_hid"> 1814 </td><td class="subject"> 입주기업 선정 안내 </td><td class="m_hid"></td><td>2026.10.07</td><td class="m_hid">94</td></tr>
</tbody></table>"""

DETAIL = """<table class="board_row_type01"><tbody>
<tr class="board_row_tit"><th colspan="4"><strong>[모집공고] 설치지원 4차</strong></th></tr>
<tr><th><strong>등록자</strong></th><td>관리자</td><th><strong>등록일</strong></th><td>2026.10.16</td></tr>
<tr><th><strong>첨부파일</strong></th><td colspan="3">
<a href="javascript:void(0);" class="down_file" onclick="fncFileDown('/atch/fileDown.do','FILE01','0','ATCH1');return false;"><u>공고문.pdf</u></a></td></tr>
<tr><td colspan="4" class="tbl_text"><div class="text_area"><p>접수기간 : 2026. 10. 20.(화) ~ 2026. 11. 3.(화)</p></div></td></tr>
</tbody></table>"""


class RapaTest(unittest.TestCase):
    def setUp(self):
        self.ad = RapaNoticeAdapter(http=None)

    def test_registered_and_since(self):
        self.assertIs(get_adapter_class("rapa_notice"), RapaNoticeAdapter)
        self.assertIsNone(self.ad.since)      # 10/27 전체 수집으로 변경

    def test_list(self):
        rows, last = self.ad.parse_list(LIST, 1)
        self.assertEqual(last, 184)                                  # 1,834건 ÷ 10
        self.assertEqual([r["post_no"] for r in rows], ["7621", "7617"])
        self.assertTrue(self.ad.is_pinned(rows[0]))
        self.assertIsNone(rows[0]["list_no"])
        self.assertFalse(self.ad.is_pinned(rows[1]))
        self.assertEqual(rows[1]["list_no"], 1814)
        self.assertEqual(rows[0]["biz"], "모집공고")
        self.assertEqual(rows[1]["list_date"], "2026-10-07")

    def test_detail(self):
        d = self.ad.parse_detail(DETAIL)
        self.assertEqual(d["posted_at"], "2026-10-16")
        self.assertEqual(d["period_raw"], "2026-10-20 ~ 2026-11-03")
        self.assertEqual(d["files"][0]["name"], "공고문.pdf")
        self.assertIn("fileSn=0", d["files"][0]["url"])
        self.assertIn("boardSeq=7621", self.ad.detail_url("7621"))


if __name__ == "__main__":
    unittest.main()


class KeepPeriodTest(unittest.TestCase):
    """첨부 판독 등으로 채운 접수기간을, 기간이 없는 목록·본문으로 다시 수집해도 지우지 않는다."""

    def test_recrawl_keeps_period(self):
        import sqlite3
        from pathlib import Path
        from app.crawler.runner import ensure_board, save_announcement
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text(encoding="utf-8"))
        ad = RapaNoticeAdapter(http=None)
        bid = ensure_board(conn, RapaNoticeAdapter)
        row = {"post_no": "1", "list_no": None, "site_status": "", "title": "t", "list_date": "2026-03-01"}
        ann, _ = save_announcement(conn, bid, ad, row, {"body": "x", "files": []}, "n")
        conn.execute("UPDATE announcements SET period_raw='2026-03-01 ~ 2026-03-20', start_at='2026-03-01', end_at='2026-03-20' WHERE ann_id=?", (ann,))
        save_announcement(conn, bid, ad, row, {"body": "x", "files": [], "period_raw": ""}, "n2")
        r = conn.execute("SELECT period_raw, start_at, end_at FROM announcements WHERE ann_id=?", (ann,)).fetchone()
        self.assertEqual(tuple(r), ("2026-03-01 ~ 2026-03-20", "2026-03-01", "2026-03-20"))

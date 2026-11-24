"""수요자 화면 항목 — 수집한 값만으로 만든 항목과 NEW 배지, 접수 상태."""
import unittest
from datetime import datetime

from app.services.mask import mask_contacts
from app.services.public import build_item, is_new, status

NOW = datetime(2026, 10, 20, 12, 0)


def row(title="2026년 모집 공고", body="가" * 100, **kw):
    base = {"ann_id": 1, "org": "기관", "org_code": "nipa", "title": title, "biz": "사업", "start_at": "2026-10-01", "end_at": "2026-10-30",
            "posted_at": "2026-10-19", "list_date": "2026-10-19", "views": 3, "attach_count": 1, "body": body, "body_len": len(body), "url": "http://x"}
    return {**base, **kw}


class NewBadgeTest(unittest.TestCase):
    def test_window(self):
        self.assertTrue(is_new("2026-10-20", NOW, 7))
        self.assertTrue(is_new("2026-10-14", NOW, 7))
        self.assertFalse(is_new("2026-10-13", NOW, 7))
        self.assertFalse(is_new("2026-10-21", NOW, 7))        # 미래 날짜는 새 공고가 아니다
        self.assertFalse(is_new(None, NOW, 7))

    def test_item_field(self):
        self.assertTrue(build_item(row(posted_at="2026-10-19"), NOW)["new"])
        self.assertFalse(build_item(row(posted_at="2026-09-01"), NOW)["new"])


class StatusTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(status("2026-10-01", "2026-10-30", "공고", "2026-10-01", NOW)["st"], "open")
        self.assertEqual(status("2026-10-01", "2026-10-22", "공고", "2026-10-01", NOW)["st"], "urgent")
        self.assertEqual(status("2026-10-25", "2026-11-30", "공고", "2026-10-01", NOW)["st"], "upcoming")
        self.assertEqual(status("2026-09-01", "2026-09-30", "공고", "2026-09-01", NOW)["st"], "ended")
        self.assertEqual(status(None, None, "공고", "2026-10-01", NOW)["st"], "always")
        self.assertEqual(status(None, None, "공고", "2024-01-01", NOW)["st"], "ended")   # 기간이 없고 게시 1년이 지남
        self.assertEqual(status("2026-10-01", "2026-12-31", "[접수마감] 공고", "2026-10-01", NOW)["st"], "ended")

    def test_d_day_label(self):
        self.assertEqual(status("2026-10-01", "2026-10-22", "공고", "2026-10-01", NOW)["label"], "D-2")
        self.assertEqual(status("2026-10-01", "2026-10-20", "공고", "2026-10-01", NOW)["label"], "오늘 마감")


class BuildItemTest(unittest.TestCase):
    def test_only_collected_values(self):
        x = build_item(row(), NOW)
        for k in ("id", "org", "title", "biz", "start", "end", "posted", "views", "files", "summary", "st", "label"):
            self.assertIn(k, x)
        for k in ("kind", "fields", "targets", "methods", "exposure", "source", "budget_per"):
            self.assertNotIn(k, x)                             # 판별 값은 없다

    def test_summary_masks_contacts_and_needs_a_body(self):
        x = build_item(row(body="문의 담당자 02-1234-5678 / a@b.kr 로 연락 바랍니다. " * 3), NOW)
        self.assertNotIn("1234-5678", x["summary"])
        self.assertNotIn("a@b.kr", x["summary"])
        self.assertEqual(build_item(row(body="짧음"), NOW)["summary"], "")

    def test_mask_contacts(self):
        self.assertEqual(mask_contacts("제 2026-0977 호"), "제 2026-0977 호")      # 공고번호는 건드리지 않는다
        self.assertIn("[전화번호]", mask_contacts("문의 010-1234-5678"))


if __name__ == "__main__":
    unittest.main()

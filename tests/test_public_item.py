"""수요자 화면 항목 — 수집한 값만으로 만든 항목과 NEW 배지, 접수 상태."""
import sqlite3
import unittest
from datetime import datetime

from app.services import labels
from app.services.mask import mask_contacts
from app.services.public import build_item, is_new, public_item, public_items, status
from tests.helpers import SCHEMA

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


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("INSERT INTO orgs(code, name, kind) VALUES ('nipa','기관','전담기관')")
    c.execute("INSERT INTO boards(org_id, code, name, list_url) VALUES (1,'nipa_business','사업공고','http://x')")
    for i in (1, 2):
        c.execute("INSERT INTO announcements(ann_id, board_id, post_no, title, body, first_seen, last_seen) VALUES (?,1,?,'공고','본문','2026-10-01','2026-10-01')",
                  (i, str(i)))
    return c


def add_field(c, ann_id, field, status, value=None, source=None, method="rule"):
    c.execute("INSERT INTO announcement_fields(ann_id, field, value, status, source, method, input_hash, extracted_at) VALUES (?,?,?,?,?,?,'h','t')",
              (ann_id, field, value, status, source, method))


class TypeAndFieldsTest(unittest.TestCase):
    CFG = {"PUBLIC_NEW_DAYS": 7}

    def test_build_item_type(self):
        self.assertEqual(build_item(row(), NOW)["type"], "미분류")                    # 라벨이 없으면 미분류
        self.assertEqual(build_item(row(**{"class": "입찰공고"}), NOW)["type"], "입찰공고")
        self.assertNotIn("sub", build_item(row(**{"class": "입찰공고", "sub": "입찰"}), NOW))   # 하위 유형은 상세에만

    def test_list_items_have_type(self):
        c = mem()
        labels.save_api(c, 1, cls="기타", sub="안내", confidence="high", reason="r", status="확정", prompt_version="v", model="m",
                        request_id="x", input_hash="h")
        items, total = public_items(c, self.CFG, NOW)
        self.assertEqual((total, {x["id"]: x["type"] for x in items}), (2, {1: "기타", 2: "미분류"}))
        self.assertTrue(all("astruct" not in x for x in items))

    def test_public_item_type_sub_fields(self):
        c = mem()
        labels.save_api(c, 1, cls="입찰공고", sub="사전규격", confidence="high", reason="r", status="확정", prompt_version="v", model="m",
                        request_id="x", input_hash="h")
        add_field(c, 1, "title", "확인", "공고", source="site")
        add_field(c, 1, "content", "확인", "개요", source="body", method="api")
        x = public_item(c, self.CFG, 1, NOW)
        self.assertEqual((x["type"], x["sub"]), ("입찰공고", "사전규격"))
        self.assertEqual([f["field"] for f in x["fields"]], ["title", "content", "qualify", "area", "period"])
        self.assertEqual([f["label"] for f in x["fields"]], ["공고명", "사업 개요", "입찰참가자격", "분야·계약방법", "입찰서 접수기간"])
        self.assertEqual([f["status"] for f in x["fields"]], ["확인", "확인", "미확인", "미확인", "미확인"])   # 행 없는 칸은 미확인
        self.assertEqual((x["fields"][0]["source_text"], x["fields"][1]["source_text"]), ("사이트 칸", "공고 본문 · AI 발췌"))
        self.assertNotIn("astruct_data", x)

    def test_public_item_unprocessed_and_other_type(self):
        c = mem()
        x = public_item(c, self.CFG, 2, NOW)
        self.assertEqual((x["type"], x["sub"], x["fields"]), ("미분류", None, []))      # 아직 정리하지 않은 공고
        labels.set_manual(c, 2, "기타", "안내", "admin")
        add_field(c, 2, "title", "확인", "공고", source="site")
        x = public_item(c, self.CFG, 2, NOW)
        self.assertEqual([f["status"] for f in x["fields"]][2:], ["해당 없음"] * 3)         # 기타 유형에 없는 칸


if __name__ == "__main__":
    unittest.main()

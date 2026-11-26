"""후속 과제(2026-11-26) — 자동화 실행 기록의 단계 요약, 유형 수정 뒤 표준 필드 다시 정리, 엑셀 유형 열, 연락처 가림 속도."""
import json
import time
import unittest
from pathlib import Path

import openpyxl

from app.services import labels
from app.services.export import ANN_HEAD, export_xlsx
from app.services.mask import mask_contacts
from tests.test_admin_labels import API, Base
from tests.test_predeploy import add_ann


class RunSummaryTest(Base):
    def test_stage_summaries_shown(self):
        summary = {"crawl": {"boards": 4, "new": 3, "errors": 0}, "attach_text": {"items": 5, "ok": 7},
                   "classify": {"확정": 12, "수동 확인": 1, "분류 보류": 0, "cost_usd": 0.0123},
                   "fields": {"done": 9, "api_items": 2, "errors": 0}}
        with self.conn() as c:
            c.execute("INSERT INTO automation_runs (trigger, started_at, ended_at, status, summary, log) VALUES (?,?,?,?,?,?)",
                      ("시험", "2026-11-26T06:00:00", "2026-11-26T06:05:00", "정상", json.dumps(summary, ensure_ascii=False), "[]"))
            c.execute("INSERT INTO automation_runs (trigger, started_at, ended_at, status, summary, log) VALUES (?,?,?,?,?,?)",
                      ("시험2", "2026-11-26T07:00:00", "2026-11-26T07:01:00", "주의",
                       json.dumps({"classify": {"skipped": "키 없음"}, "attach_text": {"errors": 1, "error": "RuntimeError: kordoc 없음"}},
                                  ensure_ascii=False), "[]"))
        self.login()
        html = self.c.get("/admin/automation").get_data(as_text=True)
        for s in ("수집 신규 3건", "첨부 글자 공고 5건 · 읽음 7개", "분류 12건 확정 · 수동 확인 1", "$0.012", "표준 필드 9건 정리 · API 2건",
                  "분류 건너뜀(키 없음)", "첨부 글자 실패", "kordoc 없음"):
            self.assertIn(s, html, s)


class ManualLabelRefreshTest(Base):
    def test_fields_recomputed_after_type_change(self):
        with self.conn() as c:
            add_ann(c, "행사 안내", post_no="1")
            labels.save_api(c, 1, cls="공모지원사업", sub="지원사업", status="확정", **API)
        self.login()
        self.c.post("/admin/notice/1/label", data={"cls": "기타", "sub": "안내"})
        with self.conn() as c:
            st = {r["field"]: r["status"] for r in c.execute("SELECT field, status FROM announcement_fields WHERE ann_id=1")}
        self.assertEqual(len(st), 5)
        for f in ("qualify", "area", "period"):            # 기타 유형에는 없는 칸
            self.assertEqual(st[f], "해당 없음", f)


class ExportTypeTest(Base):
    def test_type_columns(self):
        with self.conn() as c:
            add_ann(c, "공고 하나", post_no="1")
            add_ann(c, "공고 둘", post_no="2")
            labels.save_api(c, 1, cls="입찰공고", sub="사전규격", status="확정", **API)
        self.assertEqual(ANN_HEAD[-2:], ["유형", "하위유형"])
        with self.conn() as c:
            out = export_xlsx(c, Path(self.d.name) / "x")
        rows = list(openpyxl.load_workbook(out)["공고"].iter_rows(values_only=True))
        got = {r[3]: r[-2:] for r in rows[1:]}
        self.assertEqual(got["공고 하나"], ("입찰공고", "사전규격"))
        self.assertEqual(got["공고 둘"], ("미분류", None))


class MaskSpeedTest(unittest.TestCase):
    def test_long_text_without_spaces_is_fast(self):
        text = "가" * 50000 + "abc" * 20000
        t = time.time()
        mask_contacts(text)
        self.assertLess(time.time() - t, 1.0)

    def test_still_masks(self):
        self.assertEqual(mask_contacts("문의: kim.lee+ax@nipa.or.kr 로"), "문의: [이메일] 로")
        self.assertEqual(mask_contacts("담당자abc@x.kr"), "담당자[이메일]")      # 한글 이름은 남기고 주소만 가린다
        self.assertEqual(mask_contacts("제 2026-0977 호"), "제 2026-0977 호")


if __name__ == "__main__":
    unittest.main()

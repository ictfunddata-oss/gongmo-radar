"""3단계 W-ui — 운영 '분류·정리' 화면, 운영 상세의 유형 수정, 자동화 단계 스위치, 수요자 화면의 유형·표준 정보."""
import json
import re
import sqlite3
from contextlib import contextmanager
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import create_app
from app.automation import settings as cfgmod
from app.crawler.adapters import ADAPTERS
from app.services import admin_labels, labels
from tests.test_predeploy import add_ann

API = dict(confidence="high", reason="근거", prompt_version="classify_v2", model="m", request_id="cli:x", input_hash="h")


def add_field(conn, ann_id, field, status, value=None, **kw):
    conn.execute("INSERT INTO announcement_fields(ann_id, field, value, status, method, input_hash, extracted_at, source, source_ref, note) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", (ann_id, field, value, status, kw.get("method", "rule"), "h", "2026-11-20T10:00:00",
                                                  kw.get("source"), kw.get("source_ref"), kw.get("note")))


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        d = Path(self.d.name)
        self.db = d / "t.db"
        app = create_app({"DB_PATH": self.db, "DATA_DIR": d, "ATTACHMENT_DIR": d / "a", "EXPORT_DIR": d / "e",
                          "BANNED_TERMS_PATH": d / "b.txt", "ADMIN_ID": "admin", "VISIT_LOG": False,
                          "ADMIN_PASSWORD_HASH": generate_password_hash("test-password-1234", method="pbkdf2:sha256:1000")})
        self.c = app.test_client()

    def tearDown(self):
        self.d.cleanup()

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def login(self):
        self.c.post("/admin/login", data={"id": "admin", "password": "test-password-1234"})

    def fill(self):
        """공고 4건: 1 공모지원사업(표준 필드·충돌), 2 입찰공고, 3 분류 보류, 4 라벨 없음 + API 호출 기록."""
        with self.conn() as c:
            for i, t in enumerate(["지원사업 공모", "용역 입찰", "보류 공고", "새 공고"], 1):
                add_ann(c, t, post_no=str(i))
            labels.save_api(c, 1, cls="공모지원사업", sub="지원사업", status="확정", **API)
            labels.save_api(c, 2, cls="입찰공고", sub="입찰", status="확정", **API)
            labels.save_api(c, 3, cls=None, sub=None, status="분류 보류", **API)
            add_field(c, 1, "title", "확인", "지원사업 공모", source="site")
            add_field(c, 1, "content", "확인", "<script>alert(1)</script> 내용", source="attachment", source_ref="공고문.hwp", method="api")
            add_field(c, 1, "qualify", "미확인")
            add_field(c, 1, "period", "충돌", "2026.11.01 ~ 2026.11.30", source="body", note="첨부: 2026.12.01 마감")
            now = datetime.now().isoformat(timespec="seconds")
            c.execute("INSERT INTO llm_calls(stage, mode, model, served_model, fallback, items, input_tokens, output_tokens, cost_usd, outcome, "
                      "started_at) VALUES ('classify','sync','m','m2',1,10,1000,200,0.12,'ok',?)", (now,))
            c.execute("INSERT INTO llm_calls(stage, mode, model, items, outcome, error, started_at) VALUES ('extract','sync','m',1,'error','boom',?)",
                      (now,))
            c.commit()


class LabelsPageTest(Base):
    def test_requires_login(self):
        self.assertIn(self.c.get("/admin/labels").status_code, (302, 401, 503))

    def test_empty_db(self):
        self.login()
        r = self.c.get("/admin/labels")
        self.assertEqual(r.status_code, 200)
        self.assertIn("분류·정리", r.get_data(as_text=True))

    def test_filled_db(self):
        self.fill()
        self.login()
        r = self.c.get("/admin/labels")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("보류 공고", html)                       # 분류 보류 목록
        self.assertIn("첨부: 2026.12.01 마감", html)            # 충돌 목록
        self.assertIn("boom", html)                            # 최근 호출
        self.assertNotIn("<script>alert(1)", html)

    def test_queries(self):
        self.fill()
        with self.conn() as c:
            total = admin_labels.org_types(c)[-1]
            self.assertEqual(total["counts"], {"공모지원사업": 1, "입찰공고": 1, "기타": 0, "미분류": 2})
            self.assertEqual(dict(admin_labels.label_status(c)), {"확정": 2, "수동 확인": 0, "분류 보류": 1, "라벨 없음": 1})
            fs = {r["field"]: r["counts"] for r in admin_labels.field_status(c)}
            self.assertEqual(fs["period"]["충돌"], 1)
            self.assertEqual([r["ann_id"] for r in admin_labels.conflicts(c)], [1])
            (month, rows), (_, last) = admin_labels.api_usage(c)
            self.assertEqual({r["stage"]: (r["calls"], r["fallbacks"], r["failed"]) for r in rows}, {"classify": (1, 1, 0), "extract": (1, 0, 1)})
            self.assertEqual(last, [])


class LabelEditTest(Base):
    def test_requires_login(self):
        with self.conn() as c:
            add_ann(c, "공고")
        r = self.c.post("/admin/notice/1/label", data={"cls": "기타", "sub": "안내"})
        self.assertIn(r.status_code, (302, 401, 503))
        with self.conn() as c:
            self.assertIsNone(labels.get(c, 1))

    def test_set_manual_and_audit(self):
        with self.conn() as c:
            add_ann(c, "공고")
        self.login()
        r = self.c.post("/admin/notice/1/label", data={"cls": "입찰공고", "sub": "사전규격"}, follow_redirects=True)
        self.assertIn("유형을 고쳤습니다", r.get_data(as_text=True))
        with self.conn() as c:
            row = labels.get(c, 1)
            self.assertEqual((row["class"], row["sub"], row["source"], row["labeled_by"]), ("입찰공고", "사전규격", "manual", "admin"))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='유형 수정'").fetchone()[0], 1)
        html = self.c.get("/admin/announcements/1").get_data(as_text=True)
        self.assertIn("사전규격", html)

    def test_rejects_bad_sub(self):
        with self.conn() as c:
            add_ann(c, "공고")
        self.login()
        r = self.c.post("/admin/notice/1/label", data={"cls": "공모지원사업", "sub": "사전규격"}, follow_redirects=True)
        self.assertIn("올바르지 않습니다", r.get_data(as_text=True))
        with self.conn() as c:
            self.assertIsNone(labels.get(c, 1))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='유형 수정'").fetchone()[0], 0)
        self.assertEqual(self.c.post("/admin/notice/99/label", data={"cls": "기타", "sub": "안내"}).status_code, 404)

    def test_detail_shows_fields(self):
        self.fill()
        self.login()
        html = self.c.get("/admin/announcements/1").get_data(as_text=True)
        self.assertIn("첨부: 2026.12.01 마감", html)
        self.assertIn("&lt;script&gt;", html)


class AutomationKeysTest(Base):
    def test_new_keys_saved(self):
        self.login()
        html = self.c.get("/admin/automation").get_data(as_text=True)
        for k in ("attach_text", "classify", "fields", "fields_api", "classify_max_items"):
            self.assertIn(f'name="{k}"', html)
        self.c.post("/admin/automation/save", data={"crawl": "on", "boards": list(ADAPTERS), "classify": "on", "fields": "on", "pages": "0",
                                                    "classify_max_items": "30", "fields_api_max_items": "5000"})
        with self.conn() as c:
            s = cfgmod.load(c)
        self.assertEqual((s["attach_text"], s["classify"], s["fields"], s["fields_api"]), (False, True, True, False))
        self.assertEqual((s["classify_max_items"], s["fields_api_max_items"], s["attach_text_max_items"]), (30, 1000, 100))


class PublicPagesTest(Base):
    def test_list_has_type(self):
        self.fill()
        html = self.c.get("/").get_data(as_text=True)
        data = json.loads(re.search(r'<script[^>]*id="data"[^>]*>(.*?)</script>', html, re.S).group(1))
        self.assertEqual({x["id"]: x["type"] for x in data["items"]}, {1: "공모지원사업", 2: "입찰공고", 3: "미분류", 4: "미분류"})
        self.assertNotIn("astruct", data["items"][0])
        self.assertNotIn("sub", data["items"][0])

    def test_detail_standard_fields(self):
        self.fill()
        html = self.c.get("/notice/1").get_data(as_text=True)
        self.assertIn("공고 표준 정보", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)          # 자동 이스케이프
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("첨부: 공고문.hwp · AI 발췌", html)
        self.assertIn("원문 확인 필요", html)
        self.assertIn("다른 출처에는 다르게 적혀 있습니다: 첨부: 2026.12.01 마감", html)
        self.assertNotIn("첨부 구조화", html)
        self.assertIn("아직 정리하지 않은 공고입니다", self.c.get("/notice/2").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

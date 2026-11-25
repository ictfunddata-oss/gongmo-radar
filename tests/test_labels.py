"""2단계 — 유형 라벨(manual 보존·코드표 검사)·표준 필드 읽기·스키마 이행·자동화 새 설정 키."""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app
from app.automation import settings as cfgmod
from app.db import connect, init_schema
from app.services import fields, labels
from app.services.fields.model import FIELDS, LABELS, applies
from tests.helpers import SCHEMA

ROOT = Path(__file__).resolve().parent.parent


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
    c.execute("INSERT INTO orgs(code, name, kind) VALUES ('nia','기관','전담기관')")
    c.execute("INSERT INTO boards(org_id, code, name, list_url) VALUES (1,'nia_bid','입찰공고','http://x')")
    c.execute("INSERT INTO announcements(ann_id, board_id, post_no, title, biz, body, first_seen, last_seen) "
              "VALUES (7,1,'100','[공모] 제목','공모','본문','2026-11-01','2026-11-01')")
    c.execute("INSERT INTO attachments(ann_id, seq, name, ext, text_body, text_status, text_engine) VALUES (7,1,'공고문.hwp','hwp','첨부 글자','ok','kordoc')")
    c.execute("INSERT INTO attachments(ann_id, seq, name, ext, text_status) VALUES (7,2,'신청서.hwp','hwp','empty')")
    c.commit()
    return c


API = dict(confidence="high", reason="r", status="확정", prompt_version="classify_v2", model="m", request_id="cli:x", input_hash="h")


class LabelsTest(unittest.TestCase):
    def test_save_api_and_manual_is_kept(self):
        c = mem()
        self.assertEqual(labels.public_type(labels.get(c, 7)), "미분류")
        self.assertTrue(labels.save_api(c, 7, cls="입찰공고", sub="사전규격", **API))
        self.assertEqual(labels.public_type(labels.get(c, 7)), "입찰공고")
        labels.set_manual(c, 7, "공모지원사업", "수행기관", "admin")
        self.assertFalse(labels.save_api(c, 7, cls="기타", sub="안내", **API))      # 사람이 고친 값은 덮어쓰지 않는다
        row = labels.get(c, 7)
        self.assertEqual((row["class"], row["sub"], row["source"], row["labeled_by"]), ("공모지원사업", "수행기관", "manual", "admin"))
        log = c.execute("SELECT action, detail FROM audit_logs").fetchall()
        self.assertEqual([r["action"] for r in log], ["유형 수정"])
        self.assertIn("입찰공고/사전규격 → 공모지원사업/수행기관", log[0]["detail"])

    def test_manual_rejects_bad_codes(self):
        c = mem()
        for cls, sub in (("공모지원사업", "사전규격"), ("없는유형", "입찰"), ("기타", None)):
            with self.assertRaises(ValueError):
                labels.set_manual(c, 7, cls, sub, "admin")
        self.assertIsNone(labels.get(c, 7))

    def test_hold_is_unclassified(self):
        c = mem()
        labels.save_api(c, 7, cls=None, sub=None, **{**API, "status": "분류 보류"})
        self.assertEqual(labels.public_type(labels.get(c, 7)), "미분류")


class FieldsTest(unittest.TestCase):
    def test_model(self):
        self.assertEqual(set(LABELS), {"공모지원사업", "입찰공고", "기타", "미분류"})
        self.assertTrue(applies("공모지원사업", "qualify"))
        self.assertFalse(applies("기타", "period"))
        self.assertTrue(applies(None, "period"))

    def test_context_hash_and_load(self):
        c = mem()
        doc = fields.context(c, 7)
        self.assertEqual([a.name for a in doc.attachments], ["공고문.hwp"])          # 읽은 첨부만
        self.assertIsNone(fields.context(c, 999))
        h = fields.input_hash(doc)
        self.assertEqual(len(h), 16)
        labels.save_api(c, 7, cls="공모지원사업", sub="지원사업", **API)
        self.assertNotEqual(fields.input_hash(fields.context(c, 7)), h)             # 유형이 바뀌면 입력도 바뀐다
        self.assertEqual(fields.load(c, 7), [])
        for f in reversed(FIELDS):
            c.execute("INSERT INTO announcement_fields(ann_id, field, value, status, method, input_hash, extracted_at) "
                      "VALUES (7,?,?,'확인','rule','h','2026-11-25')", (f, f + " 값"))
        self.assertEqual([x["field"] for x in fields.load(c, 7)], list(FIELDS))


class SchemaTest(unittest.TestCase):
    TABLES = {"announcement_labels", "announcement_fields", "llm_calls"}

    def check(self, db):
        c = connect(db)
        init_schema(c)
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in c.execute("PRAGMA table_info(attachments)")}
        c.close()
        self.assertTrue(self.TABLES <= names)
        self.assertIn("text_engine", cols)

    def test_empty_db(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            self.check(Path(d) / "new.db")

    def test_old_db_without_new_column(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            db = Path(d) / "old.db"
            c = sqlite3.connect(db)
            c.executescript(SCHEMA.replace("announcement_labels", "x_labels").replace("announcement_fields", "x_fields")
                            .replace("llm_calls", "x_calls"))
            c.execute("ALTER TABLE attachments DROP COLUMN text_engine")
            c.close()
            self.check(db)

    def test_copy_of_real_db(self):
        real = ROOT / "data" / "gongmo.db"
        if not real.exists():
            self.skipTest("DB 없음")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            shutil.copy(real, Path(d) / "copy.db")
            self.check(Path(d) / "copy.db")

    def test_create_app_runs_schema(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            app = create_app({"DB_PATH": Path(d) / "t.db", "DATA_DIR": Path(d), "ATTACHMENT_DIR": Path(d) / "a", "EXPORT_DIR": Path(d) / "e"})
            with app.app_context():
                from app.db import get_db
                self.assertEqual(get_db().execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0], 0)


class AutomationKeysTest(unittest.TestCase):
    def test_new_keys(self):
        for k in ("attach_text", "classify", "fields", "fields_api"):
            self.assertIs(cfgmod.DEFAULTS[k], False)
        s, errs = cfgmod.clean({"crawl": "on", "boards": ["a"], "classify": "on", "classify_max_items": "5000", "fields_api_max_items": "x"}, ["a"])
        self.assertTrue(s["classify"])
        self.assertFalse(s["fields"])
        self.assertEqual(s["classify_max_items"], 1000)
        self.assertEqual(len(errs), 1)                     # 숫자가 아닌 값


if __name__ == "__main__":
    unittest.main()

"""원본 JSON 내보내기 — 공고 1건 = JSON 1개."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.export_json import export_json
from tests.helpers import SCHEMA


class ExportJsonTest(unittest.TestCase):
    def test_one_file_per_announcement(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO orgs (org_id, code, name) VALUES (1,'x','기관')")
        conn.execute("INSERT INTO boards (board_id, org_id, code, name) VALUES (1,1,'b','게시판')")
        conn.execute("INSERT INTO announcements (ann_id, board_id, post_no, title, body, posted_at) VALUES (1,1,'7','제목','본문','2026-03-01')")
        conn.execute("INSERT INTO announcements (ann_id, board_id, post_no, title, body, posted_at) VALUES (2,1,'a/b','제목2','','2026-03-02')")
        conn.execute("INSERT INTO attachments (ann_id, seq, name, ext) VALUES (1,1,'공고문.hwp','hwp')")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            res = export_json(conn, d)
            self.assertEqual((res["announcements"], res["attachments"]), (2, 1))
            one = json.loads((Path(d) / "b" / "7.json").read_text(encoding="utf-8"))
            self.assertEqual((one["title"], one["body"], one["body_empty"]), ("제목", "본문", False))
            self.assertEqual(one["attachments"][0]["name"], "공고문.hwp")
            self.assertFalse(one["attachments"][0]["downloaded"])
            self.assertNotIn("exposure", one)                       # 판별·노출 정보는 넣지 않는다
            self.assertTrue(json.loads((Path(d) / "b" / "a_b.json").read_text(encoding="utf-8"))["body_empty"])
            self.assertEqual(len(json.loads((Path(d) / "_index.json").read_text(encoding="utf-8"))), 2)


if __name__ == "__main__":
    unittest.main()

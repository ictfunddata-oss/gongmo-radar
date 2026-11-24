"""관리자 금칙어 관리(F-SVC-19) — 파일 추가·삭제, 경고, 점검, 최근 검색어, 화면."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import create_app
from app.services import searches

SCHEMA = (Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 16, 12, 0)


class EntryFileTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.f = Path(self.d.name) / "b.txt"
        self.f.write_text("# 설명\n나쁜말\n!나쁜말점\n", encoding="utf-8")

    def tearDown(self):
        self.d.cleanup()

    def test_add_goes_to_admin_section_and_takes_effect(self):
        b = searches.BannedList(self.f)
        self.assertFalse(b.contains("새단어"))
        ok, _ = searches.add_entry(self.f, "새 단어", "ban")
        self.assertTrue(ok)
        text = self.f.read_text(encoding="utf-8")
        self.assertIn(searches.MARK, text)
        self.assertTrue(text.index("새 단어") > text.index(searches.MARK))      # 관리자 구역에 추가
        self.assertIn("# 설명", text)                                              # 기존 설명은 보존
        self.assertTrue(self.f.with_suffix(".txt.bak").exists())                    # 백업
        import os
        os.utime(self.f, (self.f.stat().st_atime, self.f.stat().st_mtime + 5))
        self.assertTrue(b.contains("새단어"))
        added = [e for e in searches.entries(self.f) if e["added"]]
        self.assertEqual([(e["word"], e["kind"]) for e in added], [("새 단어", "ban")])

    def test_validation_and_duplicates(self):
        self.assertFalse(searches.add_entry(self.f, "가", "ban")[0])             # 2자 미만
        self.assertFalse(searches.add_entry(self.f, "x" * 31, "ban")[0])
        self.assertFalse(searches.add_entry(self.f, "나 쁜 말", "ban")[0])        # 공백 달라도 중복
        self.assertFalse(searches.add_entry(self.f, "...", "ban")[0])             # 기호뿐
        self.assertTrue(searches.add_entry(self.f, "나쁜말", "allow")[0])         # 종류가 다르면 별개

    def test_allow_and_remove(self):
        self.assertTrue(searches.add_entry(self.f, "나쁜말집", "allow")[0])
        b = searches.BannedList(self.f)
        self.assertFalse(b.contains("나쁜말집"))
        self.assertTrue(searches.remove_entry(self.f, "나쁜말", "ban")[0])
        self.assertEqual([e["word"] for e in searches.entries(self.f) if e["kind"] == "ban"], [])
        self.assertIn("!나쁜말점", self.f.read_text(encoding="utf-8"))            # 예외는 그대로
        self.assertFalse(searches.remove_entry(self.f, "없는단어", "ban")[0])


class RecentTermsTest(unittest.TestCase):
    def test_status(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.executescript(SCHEMA)
        b = searches.BannedList(lines=["나쁜말"])
        for term, n, res in [("바우처", 3, 5), ("나쁜말 검색", 5, 2), ("없는단어", 4, 0), ("한번", 1, 2)]:
            for _ in range(n):
                c.execute("INSERT INTO search_logs(term, norm, results, searched_at) VALUES (?,?,?,?)",
                          (term, term.lower(), res, (NOW - timedelta(days=1)).isoformat(timespec="seconds")))
        rows = {r["term"]: r for r in searches.recent_terms(c, b, now=NOW)}
        self.assertEqual(rows["바우처"]["status"], "표시 중")
        self.assertEqual(rows["나쁜말 검색"]["status"], "금칙어")
        self.assertEqual(rows["없는단어"]["status"], "대기")        # 결과가 0건이라 표시 후보가 아님
        self.assertEqual(rows["한번"]["status"], "대기")            # 횟수 부족
        self.assertEqual(searches.matches(b, "나 쁜 말"), ["나쁜말"])


class AdminPageTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        d = Path(self.d.name)
        self.f = d / "b.txt"
        self.f.write_text("나쁜말\n", encoding="utf-8")
        app = create_app({"DB_PATH": d / "t.db", "DATA_DIR": d, "ATTACHMENT_DIR": d / "a", "EXPORT_DIR": d / "e", "BANNED_TERMS_PATH": self.f,
                              "ADMIN_ID": "admin", "ADMIN_PASSWORD_HASH": generate_password_hash("test-password-1234", method="pbkdf2:sha256:1000")})
        self.c = app.test_client()
        self.c.post("/admin/login", data={"id": "admin", "password": "test-password-1234"})   # 운영 화면은 로그인 필요

    def tearDown(self):
        self.d.cleanup()

    def test_add_remove_test_via_pages(self):
        r = self.c.get("/admin/banned")
        self.assertEqual(r.status_code, 200)
        self.assertIn("나쁜말", r.get_data(as_text=True))
        r = self.c.post("/admin/banned/add", data={"kind": "ban", "word": "추가금칙어"}, follow_redirects=True)
        self.assertIn("추가금칙어", r.get_data(as_text=True))
        r = self.c.get("/admin/banned?test=추가 금칙어")
        self.assertIn("걸림", r.get_data(as_text=True))
        r = self.c.post("/admin/banned/remove", data={"kind": "ban", "word": "추가금칙어"}, follow_redirects=True)
        self.assertIn("삭제했습니다", r.get_data(as_text=True))
        self.assertNotIn("추가금칙어", self.f.read_text(encoding="utf-8"))

    def test_warns_when_word_is_in_titles(self):
        c = self.c
        with sqlite3.connect(Path(self.d.name) / "t.db") as db:
            db.execute("INSERT INTO orgs(code, name, kind) VALUES ('x','기관','전담기관')")
            db.execute("INSERT INTO boards(org_id, code, name, list_url) VALUES (1,'b','게시판','u')")
            db.execute("INSERT INTO announcements(board_id, post_no, title, first_seen, last_seen) VALUES (1,'1','구성기관 모집','t','t')")
        r = c.post("/admin/banned/add", data={"kind": "ban", "word": "성기"}, follow_redirects=True)
        self.assertIn("공고 제목 1건", r.get_data(as_text=True))
        self.assertNotIn("성기", self.f.read_text(encoding="utf-8"))               # 경고만 하고 저장하지 않음
        c.post("/admin/banned/add", data={"kind": "ban", "word": "성기", "force": "1"})
        self.assertIn("성기", self.f.read_text(encoding="utf-8"))                  # '그래도 추가'면 저장

    def test_recent_terms_table_and_empty(self):
        self.assertIn("아직 검색어 기록이 없습니다", self.c.get("/admin/banned").get_data(as_text=True))
        for _ in range(2):
            self.c.post("/search-log", json={"q": "인공지능 바우처", "n": 3})
        html = self.c.get("/admin/banned").get_data(as_text=True)
        self.assertIn("인공지능 바우처", html)
        self.assertIn("표시 중", html)


if __name__ == "__main__":
    unittest.main()

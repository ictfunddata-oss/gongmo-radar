"""많이 찾는 검색어(F-SVC-18) — 기록 규칙과 집계."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import create_app
from app.services import searches
from tests.test_predeploy import add_ann

SCHEMA = (Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 16, 12, 0)


def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


class RecordTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(searches.normalize("  GPU   지원 "), "GPU 지원")
        for bad in ("", "a", "x" * 31, "kim@example.com", "010-1234-5678", "https://x.kr", "www.x.kr"):
            self.assertEqual(searches.normalize(bad), "", bad)

    def test_unrecordable_is_not_saved(self):
        c = conn()
        self.assertFalse(searches.record(c, "010-1234-5678", 3, NOW))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM search_logs").fetchone()[0], 0)

    def test_old_rows_are_purged(self):
        c = conn()
        searches.record(c, "오래된", 1, NOW - timedelta(days=200))
        searches.record(c, "새 검색어", 1, NOW)
        self.assertEqual([r["term"] for r in c.execute("SELECT term FROM search_logs")], ["새 검색어"])


class TopTermsTest(unittest.TestCase):
    def fill(self, c, items):
        for term, results, days_ago in items:
            searches.record(c, term, results, NOW - timedelta(days=days_ago))

    def test_ranking_and_rules(self):
        c = conn()
        self.fill(c, [("바우처", 4, 1)] * 3 + [("SaaS", 2, 1), ("saas", 2, 2), ("SaaS", 2, 3), ("saas", 2, 3)] +
                  [("GPU", 5, 1), ("GPU", 5, 2)] + [("없는말", 0, 1)] * 5 + [("한번만", 3, 1)] + [("옛날", 3, 40)] * 4)
        top = searches.top_terms(c, days=30, limit=5, min_count=2, now=NOW)
        # 대소문자 구분 없이 묶고(SaaS 4회), 결과 0건·1회뿐·30일 밖은 뺀다. 같은 표기가 많은 쪽을 보여 줌(SaaS 3·saas 2→ 아님: SaaS 2·saas 2 동률이면 먼저 센 표기)
        self.assertEqual([t[1] for t in top], [4, 3, 2])
        self.assertEqual(top[0][0].lower(), "saas")
        self.assertEqual([t[0] for t in top[1:]], ["바우처", "GPU"])

    def test_limit_and_empty(self):
        c = conn()
        self.assertEqual(searches.top_terms(c, now=NOW), [])
        self.fill(c, [(f"검색어{i}", 1, 1) for i in range(8) for _ in range(2)])
        self.assertEqual(len(searches.top_terms(c, limit=5, now=NOW)), 5)


class RouteTest(unittest.TestCase):
    def test_post_and_display(self):
        with tempfile.TemporaryDirectory() as d:
            app = create_app({"DB_PATH": Path(d) / "t.db", "DATA_DIR": Path(d), "ATTACHMENT_DIR": Path(d) / "a", "EXPORT_DIR": Path(d) / "e"})
            with app.app_context():   # 결과 수는 서버가 다시 세므로 검색어에 맞는 공고를 넣어 둔다
                from app.db import get_db
                add_ann(get_db(), "2027 인공지능 바우처 공고")
            c = app.test_client()
            self.assertNotIn("많이 찾는 검색어", c.get("/").get_data(as_text=True))      # 기록이 없으면 숨김
            for _ in range(2):
                self.assertEqual(c.post("/search-log", json={"q": "인공지능 바우처", "n": 7}).status_code, 204)
            c.post("/search-log", json={"q": "010-1234-5678", "n": 9})                  # 기록되지 않음
            html = c.get("/").get_data(as_text=True)
            self.assertIn("많이 찾는 검색어", html)
            self.assertIn("인공지능 바우처", html)
            self.assertNotIn("1234-5678", html)


if __name__ == "__main__":
    unittest.main()


class BannedTest(unittest.TestCase):
    """금칙어 — 걸러야 할 것과 걸러서는 안 되는 정상 검색어(F-SVC-18)."""

    def setUp(self):
        self.b = searches.BannedList(Path(__file__).resolve().parent.parent / "app" / "banned_terms.txt")

    def test_blocks_variants(self):
        for t in ("시발", "시 발", "시.발", "씨~발 바우처", "FUCK", "Fuck you", "ㅅㅂ", "병신같은 공고", "개새끼들"):
            self.assertTrue(self.b.contains(t), t)

    def test_allows_normal_searches(self):
        # 공백을 없애고 검사하므로 우연히 겹치는 단어에 주의: 구성기관·애자일·한-일 베트남 등
        for t in ("바우처", "GPU", "해외진출", "입주", "SaaS", "인공지능 클라우드", "정보통신", "구성기관 모집", "애자일 교육",
                  "한-일 베트남 협력", "시발점", "시발역 안내", "디지털 콘텐츠", "AI 데이터 센터", "컨설팅"):
            self.assertFalse(self.b.contains(t), t)

    def test_no_title_in_db_is_flagged(self):
        db = Path(__file__).resolve().parent.parent / "data" / "gongmo.db"
        if not db.exists():
            self.skipTest("DB 없음")
        c = sqlite3.connect(db)
        flagged = [t for (t,) in c.execute("SELECT title FROM announcements") if self.b.contains(t)]
        self.assertEqual(flagged, [])

    def test_file_reload_and_allow_rule(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "b.txt"
            f.write_text("# 주석\n나쁜말\n!나쁜말점\n", encoding="utf-8")
            b = searches.BannedList(f)
            self.assertTrue(b.contains("나 쁜 말"))
            self.assertFalse(b.contains("나쁜말점"))              # 예외 단어
            self.assertTrue(b.contains("나쁜말점 나쁜말"))          # 예외를 뺀 나머지에 금칙어가 있으면 걸림
            f.write_text("새금칙어\n", encoding="utf-8")
            import os
            os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))
            self.assertTrue(b.contains("새 금칙어"))
            self.assertFalse(b.contains("나쁜말"))

    def test_record_and_top_terms(self):
        c, b = conn(), searches.BannedList(lines=["나쁜말"])
        self.assertFalse(searches.record(c, "나쁜말 바우처", 5, NOW, banned=b))      # 기록하지 않음
        for _ in range(3):
            searches.record(c, "바우처", 5, NOW)
            searches.record(c, "나쁜말 검색", 5, NOW)                                # 목록 없이 이미 쌓인 기록
        top = searches.top_terms(c, now=NOW, banned=b)
        self.assertEqual([t[0] for t in top], ["바우처"])                           # 반복돼도 화면에서는 빠진다
        self.assertEqual(len(searches.top_terms(c, now=NOW)), 2)                    # 금칙어 없이 보면 둘 다 나옴

    def test_route_hides_banned(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "b.txt"
            f.write_text("나쁜말\n", encoding="utf-8")
            app = create_app({"DB_PATH": Path(d) / "t.db", "DATA_DIR": Path(d), "ATTACHMENT_DIR": Path(d) / "a",
                              "EXPORT_DIR": Path(d) / "e", "BANNED_TERMS_PATH": f})
            with app.app_context():
                from app.db import get_db
                add_ann(get_db(), "클라우드 바우처 공고", "1")
                add_ann(get_db(), "나쁜 말 검색 공고", "2")
            c = app.test_client()
            for _ in range(3):
                c.post("/search-log", json={"q": "나쁜 말 검색", "n": 4})
                c.post("/search-log", json={"q": "클라우드 바우처", "n": 4})
            html = c.get("/").get_data(as_text=True)
            tags = html[html.index('class="qtags"'):].split("</div>", 1)[0]      # 공고 목록 JSON에는 제목이 들어 있으므로 검색어 띠만 본다
            self.assertIn("클라우드 바우처", tags)
            self.assertNotIn("나쁜 말 검색", tags)

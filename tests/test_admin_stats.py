"""관리자 통계·로그(방문 수·검색어 통계·운영 이력) 시험."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from app import auth, create_app
from app.db import init_schema
from app.services import admin_stats, audit, visits
from werkzeug.security import generate_password_hash

PW = "test-password-1234"
UA_PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"
UA_MO = "Mozilla/5.0 (iPhone; CPU iPhone OS 17) Mobile Safari"
NOW = datetime(2026, 11, 20, 10, 0, 0)


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    return c


class VisitsTest(unittest.TestCase):
    def test_counts_and_unique(self):
        c = mem()
        for ua, ip in ((UA_PC, "1.1.1.1"), (UA_PC, "1.1.1.1"), (UA_MO, "2.2.2.2")):
            self.assertTrue(visits.record(c, "list", 0, ua, ip, "k", now=NOW))
        visits.record(c, "detail", 7, UA_PC, "1.1.1.1", "k", now=NOW)
        s = visits.series(c, 3, now=NOW)
        self.assertEqual(len(s), 3)
        self.assertEqual((s[-1]["list"], s[-1]["detail"], s[-1]["pv"]), (3, 1, 4))
        self.assertEqual(s[-1]["uniq"], 2)          # 같은 사람(주소+브라우저)은 하루에 한 번만
        self.assertEqual(s[0]["pv"], 0)             # 방문이 없는 날은 0
        self.assertEqual(visits.devices(c, 3, now=NOW), {"pc": 3, "mobile": 1})

    def test_bots_skipped(self):
        c = mem()
        for ua in ("", "Googlebot/2.1", "python-requests/2.32", "curl/8.0"):
            self.assertFalse(visits.record(c, "list", 0, ua, "1.1.1.1", "k", now=NOW))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM visit_daily").fetchone()[0], 0)

    def test_no_personal_data_stored(self):
        c = mem()
        visits.record(c, "list", 0, UA_PC, "203.0.113.9", "k", now=NOW)
        dump = " ".join(str(tuple(r)) for t in ("visit_daily", "visit_uniq") for r in c.execute(f"SELECT * FROM {t}"))
        self.assertNotIn("203.0.113.9", dump)
        self.assertNotIn("Mozilla", dump)

    def test_hash_changes_every_day(self):
        a = visits.visitor_hash("k", "2026-11-20", "1.1.1.1", UA_PC)
        b = visits.visitor_hash("k", "2026-11-21", "1.1.1.1", UA_PC)
        self.assertNotEqual(a, b)

    def test_unique_off_and_old_hash_pruned(self):
        c = mem()
        visits.record(c, "list", 0, UA_PC, "1.1.1.1", "k", unique=False, now=NOW)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM visit_uniq").fetchone()[0], 0)
        old = NOW - timedelta(days=visits.UNIQ_KEEP_DAYS + 5)
        visits.record(c, "list", 0, UA_PC, "1.1.1.1", "k", now=old)
        visits.record(c, "list", 0, UA_PC, "9.9.9.9", "k", now=NOW)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM visit_uniq WHERE day < ?", (old.date().isoformat() + "z",)).fetchone()[0], 0)


class SearchStatsTest(unittest.TestCase):
    def test_summary_and_terms(self):
        c = mem()
        rows = [("바우처", "바우처", 12), ("바우처", "바우처", 8), ("GPU", "gpu", 0), ("gpu", "gpu", 0)]
        for t, n, r in rows:
            c.execute("INSERT INTO search_logs(term, norm, results, searched_at) VALUES (?,?,?,?)", (t, n, r, NOW.isoformat(timespec="seconds")))
        c.commit()
        s = admin_stats.search_summary(c, 7, now=NOW)
        self.assertEqual((s["total"], s["distinct"], s["zero"]), (4, 2, 2))
        self.assertAlmostEqual(s["zero_rate"], 0.5)
        self.assertEqual(len(s["series"]), 7)
        terms = admin_stats.search_terms(c, 7, None, now=NOW)
        self.assertEqual([t["count"] for t in terms], [2, 2])
        zero = admin_stats.search_terms(c, 7, None, only_zero=True, now=NOW)
        self.assertEqual([t["term"].lower() for t in zero], ["gpu"])


class AuditTest(unittest.TestCase):
    def test_log_and_prune(self):
        c = mem()
        audit.log(c, "admin", "규칙 추가", "규칙 A", "title words", now=NOW - timedelta(days=audit.KEEP_DAYS + 3))
        audit.log(c, "admin", "노출로 변경", "공고 1", now=NOW)
        total, rows, actions = admin_stats.audit_rows(c, 30, 0)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["action"], "노출로 변경")
        self.assertEqual(actions, ["노출로 변경"])


class WebTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        d = Path(self.d.name)
        (d / "b.txt").write_text("나쁜말\n", encoding="utf-8")
        self.app = create_app({"DB_PATH": d / "t.db", "DATA_DIR": d, "ATTACHMENT_DIR": d / "a", "EXPORT_DIR": d / "e",
                               "BANNED_TERMS_PATH": d / "b.txt", "ADMIN_ID": "admin",
                               "ADMIN_PASSWORD_HASH": generate_password_hash(PW, method="pbkdf2:sha256:1000")})
        self.c = self.app.test_client()
        auth._FAILS.clear()
        p = mock.patch.object(auth.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.d.cleanup()

    def login(self):
        return self.c.post("/admin/login", data={"id": "admin", "password": PW})

    def db(self):
        c = sqlite3.connect(self.app.config["DB_PATH"])
        c.row_factory = sqlite3.Row
        return c

    def test_public_visit_counted_but_not_bots_or_admin(self):
        self.c.get("/", headers={"User-Agent": UA_PC})
        self.c.get("/", headers={"User-Agent": "Googlebot/2.1"})
        self.assertEqual(self.db().execute("SELECT COALESCE(SUM(views),0) FROM visit_daily").fetchone()[0], 1)
        self.login()
        self.c.get("/", headers={"User-Agent": UA_PC})                    # 관리자가 로그인한 채 본 것은 세지 않는다
        self.assertEqual(self.db().execute("SELECT COALESCE(SUM(views),0) FROM visit_daily").fetchone()[0], 1)

    def test_visit_log_can_be_turned_off(self):
        self.app.config["VISIT_LOG"] = False
        self.c.get("/", headers={"User-Agent": UA_PC})
        self.assertEqual(self.db().execute("SELECT COUNT(*) FROM visit_daily").fetchone()[0], 0)

    def test_pages_need_login(self):
        for path in ("/admin/dashboard", "/admin/searches", "/admin/logs"):
            self.assertEqual(self.c.get(path).status_code, 302, path)

    def test_pages_render(self):
        self.login()
        self.c.get("/", headers={"User-Agent": UA_PC})
        for path in ("/admin/dashboard", "/admin/dashboard?days=7", "/admin/searches", "/admin/searches?zero=1",
                     "/admin/logs", "/admin/logs?t=crawl&f=issue", "/admin/logs?t=auto", "/admin/logs?t=audit", "/admin/logs?t=nope"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 200, path)
        self.assertIn("운영 통계", self.c.get("/admin/dashboard").get_data(as_text=True))

    def test_csv_download(self):
        self.login()
        r = self.c.get("/admin/searches?format=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertTrue(r.get_data(as_text=True).lstrip("﻿").startswith("검색어"))

    def test_login_and_changes_are_audited(self):
        self.c.post("/admin/login", data={"id": "admin", "password": "wrong"})
        self.c.post("/admin/login", data={"id": "my-secret-pw", "password": "x"})    # 아이디 칸에 적은 값은 남기지 않는다
        self.login()
        self.c.post("/admin/banned/add", data={"word": "새금칙어"})
        rows = [dict(r) for r in self.db().execute("SELECT actor, action, target, detail FROM audit_logs ORDER BY log_id")]
        self.assertEqual([r["action"] for r in rows], ["로그인 실패", "로그인 실패", "로그인", "금칙어 추가"])
        self.assertEqual(rows[1]["actor"], "(다른 아이디)")
        self.assertNotIn("my-secret-pw", str(rows))


if __name__ == "__main__":
    unittest.main()

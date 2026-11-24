"""관리자 로그인(F-SVC-20) — 운영 화면·운영용 API 보호, 로그인 실패 제한, 공개 화면은 열려 있음."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from werkzeug.security import generate_password_hash

from app import auth, create_app

PW = "test-password-1234"


def make_app(d, hashed=True):
    d = Path(d)
    cfg = {"DB_PATH": d / "t.db", "DATA_DIR": d, "ATTACHMENT_DIR": d / "a", "EXPORT_DIR": d / "e",
           "BANNED_TERMS_PATH": d / "b.txt", "ADMIN_ID": "admin",
           "ADMIN_PASSWORD_HASH": generate_password_hash(PW, method="pbkdf2:sha256:1000") if hashed else ""}
    (d / "b.txt").write_text("나쁜말\n", encoding="utf-8")
    return create_app(cfg)


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.app = make_app(self.d.name)
        self.c = self.app.test_client()
        auth._FAILS.clear()
        patcher = mock.patch.object(auth.time, "sleep")   # 실패 지연(0.4초)을 시험에서는 건너뜀
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.d.cleanup()

    def login(self, pw=PW, user="admin", **kw):
        return self.c.post("/admin/login", data={"id": user, "password": pw, **kw})

    def test_admin_pages_need_login(self):
        for path in ("/admin/", "/admin/banned", "/admin/dashboard", "/admin/announcements/1"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/admin/login", r.headers["Location"])
        self.assertEqual(self.c.post("/admin/banned/add", data={"word": "새단어"}).status_code, 302)   # 쓰기 요청도 막힘
        self.assertNotIn("새단어", (Path(self.d.name) / "b.txt").read_text(encoding="utf-8"))

    def test_admin_api_is_protected_but_public_api_is_open(self):
        for path in ("/api/announcements", "/api/announcements/1", "/api/stats"):
            self.assertEqual(self.c.get(path).status_code, 401, path)
        self.assertEqual(self.c.get("/api/public/announcements").status_code, 200)

    def test_public_pages_stay_open(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertEqual(self.c.post("/search-log", json={"q": "바우처", "n": 1}).status_code, 204)

    def test_login_flow(self):
        self.assertEqual(self.c.get("/admin/login").status_code, 200)
        r = self.login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/admin/banned").status_code, 200)
        self.assertEqual(self.c.get("/api/stats").status_code, 200)
        r = self.c.post("/admin/logout")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/admin/banned").status_code, 302)           # 로그아웃하면 다시 막힘

    def test_wrong_credentials(self):
        self.assertEqual(self.login(pw="틀린비밀번호").status_code, 401)
        self.assertEqual(self.login(user="other").status_code, 401)
        self.assertEqual(self.c.get("/admin/banned").status_code, 302)

    def test_lockout_after_repeated_failures(self):
        for _ in range(auth.MAX_FAILS):
            self.assertEqual(self.login(pw="x").status_code, 401)
        r = self.login()                                                          # 맞는 비밀번호도 잠금 중에는 거절
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.c.get("/admin/banned").status_code, 302)

    def test_next_is_limited_to_admin_paths(self):
        r = self.login(next="/admin/banned")
        self.assertTrue(r.headers["Location"].endswith("/admin/banned"))
        for bad in ("https://evil.example/x", "//evil.example", "/other", r"/admin\..\x"):
            self.c.post("/admin/logout")
            r = self.login(next=bad)
            self.assertTrue(r.headers["Location"].endswith("/admin/"), bad)

    def test_session_expires(self):
        self.login()
        with self.c.session_transaction() as s:
            s["exp"] = 1                                                          # 이미 지난 시각
        self.assertEqual(self.c.get("/admin/banned").status_code, 302)

    def test_blocked_when_password_not_set(self):
        d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        try:
            c = make_app(d.name, hashed=False).test_client()
            self.assertEqual(c.get("/admin/").status_code, 503)                   # 막힌 채로 설정 안내
            self.assertEqual(c.get("/admin/login").status_code, 503)
            self.assertEqual(c.post("/admin/login", data={"id": "admin", "password": ""}).status_code, 503)
            self.assertEqual(c.get("/api/stats").status_code, 503)
            self.assertEqual(c.get("/").status_code, 200)
        finally:
            d.cleanup()


class EnvWriterTest(unittest.TestCase):
    def test_set_env_replaces_and_appends(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            f = Path(d) / ".env"
            f.write_text("# 설명\nSECRET_KEY=abc\nOTHER=1\n", encoding="utf-8")
            auth.set_env(f, {"SECRET_KEY": "new", "ADMIN_PASSWORD_HASH": "'h$x'"})
            self.assertEqual(f.read_text(encoding="utf-8").splitlines(), ["# 설명", "SECRET_KEY=new", "OTHER=1", "ADMIN_PASSWORD_HASH='h$x'"])


if __name__ == "__main__":
    unittest.main()

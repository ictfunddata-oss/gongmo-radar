"""자동화(ADR-038) — 설정 검증, 예약 시각 계산, 중복 실행 방지, 파이프라인, 관리자 화면."""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from werkzeug.security import generate_password_hash

from app import create_app
from app.automation import settings as cfgmod
from app.automation.pipeline import acquire, is_running, release
from tests.helpers import SCHEMA

BOARDS = ["nipa_business", "nia_bid", "rapa_notice"]


def mem():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def S(**kw):
    return {**cfgmod.DEFAULTS, "enabled": True, **kw}


class SettingsTest(unittest.TestCase):
    def test_clean_valid_and_errors(self):
        s, errs = cfgmod.clean({"enabled": "on", "days": ["0", "2", "x", "9"], "times": ["18:30", "6:05", "", "18:30"],
                                "boards": BOARDS, "pages": "5", "crawl": "on"}, BOARDS)
        self.assertEqual(errs, [])
        self.assertEqual(s["days"], [0, 2])
        self.assertEqual(s["times"], ["06:05", "18:30"])          # 정렬·중복 제거·0 채움
        self.assertIsNone(s["boards"])                            # 전부 선택 = 모든 게시판
        self.assertEqual(s["pages"], 5)
        self.assertEqual(cfgmod.clean({"pages": "999"}, BOARDS)[0]["pages"], 200)              # 범위 보정
        _, errs = cfgmod.clean({"enabled": "on", "days": [], "times": ["25:99"]}, BOARDS)
        self.assertEqual(len(errs), 3)                            # 잘못된 시각 + 요일 없음 + 시각 없음
        s, errs = cfgmod.clean({"enabled": "", "days": [], "times": []}, BOARDS)
        self.assertEqual(errs, [])                                # 꺼져 있으면 비어 있어도 저장 가능

    def test_defaults_are_safe(self):
        self.assertFalse(cfgmod.DEFAULTS["enabled"])
        self.assertFalse(cfgmod.DEFAULTS["attachments"])

    def test_save_load(self):
        conn = mem()
        self.assertEqual(cfgmod.load(conn), cfgmod.DEFAULTS)
        cfgmod.save(conn, S(times=["07:00"]))
        self.assertEqual(cfgmod.load(conn)["times"], ["07:00"])


class ScheduleTest(unittest.TestCase):
    def test_next_run(self):
        s = S(days=[0, 4], times=["06:00", "18:00"])           # 월·금
        mon = datetime(2026, 10, 19, 7, 0)                      # 2026-10-19는 월요일
        self.assertEqual(cfgmod.next_run(s, mon), datetime(2026, 10, 19, 18, 0))
        self.assertEqual(cfgmod.next_run(s, datetime(2026, 10, 19, 19, 0)), datetime(2026, 10, 23, 6, 0))   # 다음은 금요일
        self.assertIsNone(cfgmod.next_run({**s, "enabled": False}, mon))

    def test_due_slot_and_catchup(self):
        s = S(days=[0], times=["06:00"])
        self.assertEqual(cfgmod.due_slot(s, None, datetime(2026, 10, 19, 6, 0, 20)), "2026-10-19 06:00")
        self.assertIsNone(cfgmod.due_slot(s, "2026-10-19 06:00", datetime(2026, 10, 19, 6, 5)))   # 이미 실행함
        self.assertEqual(cfgmod.due_slot(s, None, datetime(2026, 10, 19, 6, 50)), "2026-10-19 06:00")   # 60분 이내 따라잡기
        self.assertIsNone(cfgmod.due_slot(s, None, datetime(2026, 10, 19, 7, 30)))                  # 너무 늦으면 건너뜀
        self.assertIsNone(cfgmod.due_slot(s, None, datetime(2026, 10, 20, 6, 0)))                   # 화요일은 쉬는 날
        self.assertIsNone(cfgmod.due_slot({**s, "enabled": False}, None, datetime(2026, 10, 19, 6, 0)))


class AutostartTest(unittest.TestCase):
    def test_only_web_server_starts_scheduler(self):
        from app.automation.scheduler import flask_command, should_autostart
        on = {"AUTOMATION_SCHEDULER": True}
        self.assertEqual(flask_command(["--app", "run", "run", "--port", "5000"]), "run")
        self.assertEqual(flask_command(["--app", "run", "crawl", "--board", "nia_bid"]), "crawl")
        self.assertTrue(should_autostart(on, ["flask", "--app", "run", "run", "--port", "5000"]))
        self.assertFalse(should_autostart(on, ["flask", "--app", "run", "crawl"]))                  # 관리 명령에서는 시작 안 함
        self.assertFalse(should_autostart(on, ["flask", "--app", "run", "automation-run"]))
        self.assertFalse(should_autostart({"AUTOMATION_SCHEDULER": False}, ["flask", "--app", "run", "run"]))
        self.assertTrue(should_autostart(on, ["C:/x/run.py"]))                                      # python run.py


class LockAndPipelineTest(unittest.TestCase):
    def test_lock_prevents_double_run(self):
        conn = mem()
        self.assertTrue(acquire(conn, "A"))
        self.assertTrue(is_running(conn))
        self.assertFalse(acquire(conn, "B"))                    # 다른 소유자는 못 잡음
        self.assertTrue(acquire(conn, "A"))                     # 같은 소유자는 갱신 가능
        release(conn, "A")
        self.assertFalse(is_running(conn))
        self.assertTrue(acquire(conn, "B"))

    def test_pipeline_runs_without_crawl_and_records_the_run(self):
        from app.automation.pipeline import run_pipeline
        conn = mem()
        s = S(crawl=False)                                       # 수집을 끄면 네트워크 없이 기록만 남는다
        run_id, status, summary = run_pipeline({}, "테스트", settings=s, conn=conn)
        self.assertEqual(status, "정상")
        self.assertEqual(summary, {})
        row = conn.execute("SELECT status, trigger FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
        self.assertEqual((row["status"], row["trigger"]), ("정상", "테스트"))
        self.assertFalse(is_running(conn))                       # 끝나면 잠금 해제


class PageTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        d = Path(self.d.name)
        app = create_app({"DB_PATH": d / "t.db", "DATA_DIR": d, "ATTACHMENT_DIR": d / "a", "EXPORT_DIR": d / "e",
                          "BANNED_TERMS_PATH": d / "b.txt", "ADMIN_ID": "admin",
                          "ADMIN_PASSWORD_HASH": generate_password_hash("test-password-1234", method="pbkdf2:sha256:1000")})
        self.app, self.c = app, app.test_client()

    def tearDown(self):
        self.d.cleanup()

    def login(self):
        self.c.post("/admin/login", data={"id": "admin", "password": "test-password-1234"})

    def test_requires_login(self):
        self.assertIn(self.c.get("/admin/automation").status_code, (302, 401, 503))
        self.assertIn(self.c.post("/admin/automation/run").status_code, (302, 401, 503))
        self.assertIn(self.c.post("/admin/automation/save", data={"enabled": "on"}).status_code, (302, 401, 503))

    def test_save_and_show(self):
        self.login()
        html = self.c.get("/admin/automation").get_data(as_text=True)
        self.assertIn("자동화 설정", html)
        self.assertIn("꺼짐", html)
        r = self.c.post("/admin/automation/save", data={"enabled": "on", "days": ["0", "1"], "t1": "06:30", "boards": BOARDS,
                                                          "crawl": "on", "pages": "0"}, follow_redirects=True)
        html = r.get_data(as_text=True)
        self.assertIn("설정을 저장했습니다", html)
        self.assertIn("켜짐", html)
        with sqlite3.connect(Path(self.d.name) / "t.db") as db:
            s = cfgmod.load(db)
        self.assertEqual((s["enabled"], s["times"], s["days"]), (True, ["06:30"], [0, 1]))
        # 잘못된 입력은 저장하지 않음
        r = self.c.post("/admin/automation/save", data={"enabled": "on", "days": ["0"], "t1": "99:99"}, follow_redirects=True)
        self.assertIn("올바른 시각", r.get_data(as_text=True))
        with sqlite3.connect(Path(self.d.name) / "t.db") as db:
            self.assertEqual(cfgmod.load(db)["times"], ["06:30"])


if __name__ == "__main__":
    unittest.main()

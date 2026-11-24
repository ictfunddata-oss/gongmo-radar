"""예약 실행기 — 서버 안에서 15초마다 설정을 보고, 예약 시각이 되면 파이프라인을 돌린다.

- 같은 DB를 여러 프로세스(개발 서버 재시작, 여러 워커)가 쓰더라도 잠금 덕분에 한 번에 하나만 실행한다.
- 서버를 따로 두고 싶으면 웹에서는 AUTOMATION_SCHEDULER=0 으로 끄고, `flask --app run automation-daemon` 을 별도 서비스로 띄운다.
- 작업 스케줄러(cron·Windows 작업 스케줄러)를 쓰고 싶으면 `flask --app run automation-run` 을 예약한다.
"""
import sys
import threading
import time
from datetime import datetime

from ..db import connect
from . import settings as cfgmod
from .pipeline import is_running, run_pipeline

TICK = 15
_started = False
_lock = threading.Lock()


def flask_command(argv):
    """`flask --app run <명령> …` 에서 명령 이름을 돌려준다(`--app` 값 'run'을 명령으로 착각하지 않는다)."""
    skip = False
    for a in argv:
        if skip:
            skip = False
        elif a in ("--app", "-A", "--env-file", "-e", "--debug"):
            skip = a != "--debug"
        elif a.startswith("-"):
            continue
        else:
            return a
    return None


def should_autostart(cfg, argv=None):
    """웹 서버로 뜰 때만 자동 시작한다(`flask crawl` 같은 관리 명령이나 테스트에서는 시작하지 않는다)."""
    if not cfg.get("AUTOMATION_SCHEDULER"):
        return False
    argv = sys.argv if argv is None else argv
    return (flask_command(argv[1:]) == "run" or any(m in sys.modules for m in ("gunicorn", "waitress"))
            or argv[0].endswith("run.py"))


def tick(cfg, now=None):
    """한 번 점검해 실행할 예약이 있으면 실행한다. → 실행했으면 슬롯 문자열"""
    now = now or datetime.now()
    conn = connect(cfg["DB_PATH"])
    try:
        s = cfgmod.load(conn)
        row = conn.execute("SELECT value FROM app_kv WHERE key=?", (cfgmod.KEY_LAST_SLOT,)).fetchone()
        slot = cfgmod.due_slot(s, row[0] if row else None, now)
        if not slot or is_running(conn):
            return None
        conn.execute("INSERT INTO app_kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (cfgmod.KEY_LAST_SLOT, slot))
        conn.commit()
        run_pipeline(cfg, f"예약 {slot}", settings=s, conn=conn)
        return slot
    finally:
        conn.close()


def loop(cfg, stop=None):
    while not (stop and stop.is_set()):
        try:
            tick(cfg)
        except Exception as e:  # noqa: BLE001 — 한 번 실패해도 예약기는 계속 돈다
            print(f"[automation] 예약 점검 오류: {type(e).__name__}: {e}", flush=True)
        time.sleep(TICK)


def start(app):
    global _started
    with _lock:
        if _started:
            return False
        _started = True
    cfg = dict(app.config)
    threading.Thread(target=loop, args=(cfg,), daemon=True, name="automation-scheduler").start()
    return True


def run_in_background(cfg, trigger):
    """'지금 실행' — 화면 요청을 막지 않도록 별도 스레드에서 돌린다. → 시작했으면 True, 이미 실행 중이면 False"""
    conn = connect(cfg["DB_PATH"])
    try:
        if is_running(conn):
            return False
    finally:
        conn.close()
    threading.Thread(target=lambda: run_pipeline(dict(cfg), trigger), daemon=True, name="automation-manual").start()
    return True

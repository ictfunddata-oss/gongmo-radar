"""자동화 파이프라인 — 등록한 게시판의 새 공고를 수집한다(필요하면 첨부도 받는다).

- 한 게시판이 실패해도 다음 게시판은 계속한다(결과는 게시판별로 기록).
- 실행 중에는 잠금(automation_lock)에 박동을 남겨 다른 프로세스가 동시에 돌지 못하게 한다.
"""
import json
import os
import socket
import sqlite3
import threading
from datetime import datetime, timedelta

from ..crawler import crawl
from ..crawler.adapters import ADAPTERS
from ..crawler.utils import now_iso
from ..db import connect
from . import settings as cfgmod

LOCK_TTL = timedelta(seconds=180)   # 박동이 이보다 오래 멈춰 있으면 죽은 실행으로 보고 잠금을 넘겨받는다
HEARTBEAT_SEC = 30                  # 박동 스레드 간격. 한 단계가 오래 걸려도 잠금을 지킨다


def owner_id():
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire(conn, owner):
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT owner, heartbeat FROM automation_lock WHERE id=1").fetchone()
    now = datetime.now()
    if row and row["owner"] and row["owner"] != owner and now - datetime.fromisoformat(row["heartbeat"]) < LOCK_TTL:
        conn.execute("ROLLBACK")
        return False
    conn.execute("INSERT INTO automation_lock (id, owner, heartbeat) VALUES (1,?,?) "
                 "ON CONFLICT(id) DO UPDATE SET owner=excluded.owner, heartbeat=excluded.heartbeat",
                 (owner, now.isoformat(timespec="seconds")))
    conn.execute("COMMIT")
    return True


def beat(conn, owner):
    conn.execute("UPDATE automation_lock SET heartbeat=? WHERE id=1 AND owner=?", (now_iso(), owner))
    conn.commit()


def release(conn, owner):
    conn.execute("UPDATE automation_lock SET owner=NULL WHERE id=1 AND owner=?", (owner,))
    conn.commit()


class Heartbeat:
    """잠금을 쥔 동안 자기 DB 연결로 interval초마다 박동을 남기는 스레드."""

    def __init__(self, db_path, owner, interval=HEARTBEAT_SEC):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(db_path, owner, interval), daemon=True, name="automation-heartbeat")

    def _run(self, db_path, owner, interval):
        conn = connect(db_path)
        try:
            while not self._stop.wait(interval):
                try:
                    beat(conn, owner)
                except sqlite3.Error:
                    conn.rollback()     # 쓰기가 막혀도 다음 박동에서 다시 시도한다
        finally:
            conn.close()

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join()


def is_running(conn):
    row = conn.execute("SELECT owner, heartbeat FROM automation_lock WHERE id=1").fetchone()
    return bool(row and row["owner"] and datetime.now() - datetime.fromisoformat(row["heartbeat"]) < LOCK_TTL)


def run_pipeline(cfg, trigger, settings=None, conn=None, heartbeat_sec=HEARTBEAT_SEC):
    """파이프라인을 한 번 실행하고 automation_runs 에 기록한다. → (run_id, 상태, 요약), 이미 실행 중이면 None"""
    own = conn is None
    conn = conn or connect(cfg["DB_PATH"])
    owner = owner_id()
    got = False
    started = None
    hb = None
    try:
        if not acquire(conn, owner):
            return None
        got = True
        if cfg.get("DB_PATH"):   # 연결만 넘겨받은 경우(메모리 DB 테스트)는 박동 스레드가 열 DB가 없다
            hb = Heartbeat(cfg["DB_PATH"], owner, heartbeat_sec).start()
        s = settings or cfgmod.load(conn)
        started = now_iso()
        run_id = conn.execute("INSERT INTO automation_runs (trigger, started_at, status, summary, log) VALUES (?,?,?,?,?)",
                              (trigger, started, "실행 중", "{}", "[]")).lastrowid
        conn.commit()
        log, summary, problems = [], {}, 0

        def say(msg):
            log.append(f"{datetime.now():%H:%M:%S} {msg}")
            conn.execute("UPDATE automation_runs SET log=?, summary=? WHERE run_id=?",
                         (json.dumps(log[-300:], ensure_ascii=False), json.dumps(summary, ensure_ascii=False), run_id))
            conn.commit()
            beat(conn, owner)

        boards = s["boards"] if s["boards"] is not None else list(ADAPTERS)
        # 수집
        if s["crawl"]:
            res = {"boards": 0, "new": 0, "errors": 0}
            for code in boards:
                if code not in ADAPTERS:
                    continue
                try:
                    r = crawl(conn, cfg, code, mode="incremental", pages=s["pages"] or None, download=s["attachments"], echo=False)
                    res["boards"] += 1
                    res["new"] += r["new"]
                    res["errors"] += r["errors"]
                    say(f"수집 {code}: 신규 {r['new']}건 · 갱신 {r['updated']}건 · 오류 {r['errors']}건 ({r['status']})")
                except Exception as e:  # noqa: BLE001 — 한 게시판 실패로 전체를 멈추지 않는다
                    conn.rollback()
                    res["errors"] += 1
                    say(f"수집 {code} 실패: {type(e).__name__}: {e}")
            summary["crawl"] = res
            problems += res["errors"] > 0
        status = "주의" if problems else "정상"
        conn.execute("UPDATE automation_runs SET ended_at=?, status=?, summary=?, log=? WHERE run_id=?",
                     (now_iso(), status, json.dumps(summary, ensure_ascii=False), json.dumps(log[-300:], ensure_ascii=False), run_id))
        conn.commit()
        return run_id, status, summary
    except Exception as e:  # noqa: BLE001
        if got and started:
            try:
                conn.rollback()
                row = conn.execute("SELECT log FROM automation_runs WHERE status='실행 중' AND started_at=? ORDER BY run_id DESC LIMIT 1",
                                   (started,)).fetchone()
                lines = (json.loads(row["log"]) if row else []) + [f"중단: {type(e).__name__}: {e}"]
                conn.execute("UPDATE automation_runs SET ended_at=?, status='오류', log=? WHERE status='실행 중' AND started_at=?",
                             (now_iso(), json.dumps(lines, ensure_ascii=False), started))
                conn.commit()
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        try:
            if hb:
                hb.stop()
            if got:
                release(conn, owner)
        finally:
            if own:
                conn.close()

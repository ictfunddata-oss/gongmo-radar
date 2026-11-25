"""배포 전 버그 5건(00 6장 1단계) — 각 문제를 재현하는 테스트."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from flask import request

from app import create_app
from app.config import check_secret
from app.db import connect
from tests.helpers import SCHEMA


def tmp_app(d, **kw):
    return create_app({"DB_PATH": Path(d) / "t.db", "DATA_DIR": Path(d), "ATTACHMENT_DIR": Path(d) / "a", "EXPORT_DIR": Path(d) / "e", **kw})


def add_ann(conn, title, post_no="1"):
    conn.execute("INSERT OR IGNORE INTO orgs(code, name, kind) VALUES ('nipa','정보통신산업진흥원','전담기관')")
    conn.execute("INSERT OR IGNORE INTO boards(org_id, code, name, list_url) VALUES (1,'nipa_business','사업공고','http://x')")
    conn.execute("INSERT INTO announcements(board_id, post_no, title, body, first_seen, last_seen) VALUES (1,?,?,'본문','2026-11-01','2026-11-01')",
                 (post_no, title))
    conn.commit()


class DownloadLockTest(unittest.TestCase):
    """1. 첨부를 받는 동안 DB 쓰기 트랜잭션이 열려 있지 않아야 한다."""

    def test_other_connection_can_write_during_download(self):
        from app.crawler import runner
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:   # Windows: 닫힌 뒤에도 WAL 파일이 잠시 잡혀 있을 수 있다
            db = Path(d) / "t.db"
            conn = connect(db)
            conn.executescript(SCHEMA)

            class Adapter:
                code = "nipa_business"
                org_code, org_name, org_kind, board_name, list_url, since = "nipa", "기관", "전담기관", "게시판", "http://x", None

                def __init__(self, http):
                    pass

                def list_page_url(self, page):
                    return "http://x/list"

                def detail_url(self, post_no):
                    return f"http://x/{post_no}"

                def fetch_list(self, page):
                    return [{"post_no": "1", "title": "공고", "list_date": "2026-11-01"}], 1

                def fetch_detail(self, post_no):
                    return {"body": "본문", "files": [{"seq": 1, "name": "a.hwp", "ext": "hwp", "size_text": "", "size_bytes": 0, "url": "http://x/f"}]}

                def is_pinned(self, row):
                    return False

            seen = []

            def fake_download(conn_, http, adapter, ann_id, post_no, cfg, log, only_seqs=None):
                other = sqlite3.connect(db, timeout=0.2)
                try:
                    other.execute("INSERT INTO search_logs(term, norm, results, searched_at) VALUES ('a','a',1,'2026-11-01')")
                    other.commit()
                    seen.append("ok")
                except sqlite3.OperationalError as e:
                    seen.append(str(e))
                finally:
                    other.close()
                return 0

            cfg = {"DOWNLOAD_ATTACHMENTS": True, "CRAWL_DELAY": 0, "ROBOTS_CHECK": False, "ATTACHMENT_DIR": Path(d), "ATTACH_MAX_MB": 1}
            with mock.patch.object(runner, "get_adapter_class", return_value=Adapter), \
                    mock.patch.object(runner, "download_missing", side_effect=fake_download):
                res = runner.crawl(conn, cfg, "nipa_business", echo=False)
            self.assertEqual(seen, ["ok"])
            self.assertEqual(res["new"], 1)
            conn.close()


class AttachTextLockTest(unittest.TestCase):
    """1-b. 첨부 글자를 읽는 동안(kordoc은 느리다) DB 쓰기 트랜잭션이 열려 있지 않아야 한다(7단계 화면 확인에서 발견)."""

    def test_other_connection_can_write_while_reading_next_file(self):
        from app.services import attach_text, extract
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            db = Path(d) / "t.db"
            conn = connect(db)
            conn.executescript(SCHEMA)
            add_ann(conn, "공고")
            for seq in (1, 2):
                (Path(d) / f"{seq}.hwp").write_bytes(b"x")
                conn.execute("INSERT INTO attachments(ann_id, seq, name, ext, file_path) VALUES (1,?,?,'hwp',?)", (seq, f"공고문{seq}.hwp", f"{seq}.hwp"))
            conn.commit()
            seen = []

            def fake_read(path, ext, cfg):
                other = sqlite3.connect(db, timeout=0.2)
                try:
                    other.execute("INSERT INTO search_logs(term, norm, results, searched_at) VALUES ('a','a',1,'2026-11-01')")
                    other.commit()
                    seen.append("ok")
                except sqlite3.OperationalError as e:
                    seen.append(str(e))
                finally:
                    other.close()
                return "글자" * 100, "ok", "kordoc"

            cfg = {"ATTACHMENT_DIR": Path(d), "ATTACH_TEXT_FILES": 3}
            with mock.patch.object(extract, "read_text", side_effect=fake_read):
                attach_text.process(conn, cfg, [1], download=False, echo=False)
            self.assertEqual(seen, ["ok", "ok"])
            conn.close()


class HeartbeatTest(unittest.TestCase):
    """2. 한 단계가 오래 걸려도 박동 스레드가 잠금 박동을 갱신해야 한다."""

    def test_heartbeat_updates_during_long_step(self):
        from app.automation import pipeline
        from app.automation import settings as cfgmod
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:   # Windows: 닫힌 뒤에도 WAL 파일이 잠시 잡혀 있을 수 있다
            db = Path(d) / "t.db"
            conn = connect(db)
            conn.executescript(SCHEMA)
            seen = {}

            def slow_crawl(c, cfg, code, **kw):
                c.execute("UPDATE automation_lock SET heartbeat='2000-01-01T00:00:00' WHERE id=1")
                c.commit()
                time.sleep(0.3)
                other = connect(db)
                seen["hb"] = other.execute("SELECT heartbeat FROM automation_lock WHERE id=1").fetchone()[0]
                other.close()
                return {"new": 0, "updated": 0, "errors": 0, "status": "정상"}

            s = {**cfgmod.DEFAULTS, "boards": ["nipa_business"]}
            with mock.patch.object(pipeline, "crawl", side_effect=slow_crawl):
                out = pipeline.run_pipeline({"DB_PATH": db}, "시험", settings=s, conn=conn, heartbeat_sec=0.05)
            self.assertIsNotNone(out)
            self.assertNotEqual(seen["hb"], "2000-01-01T00:00:00")
            self.assertFalse(pipeline.is_running(conn))      # 끝나면 잠금을 놓는다
            conn.close()


class SecretKeyTest(unittest.TestCase):
    """3. 운영 진입점은 약한 SECRET_KEY로 뜨지 않아야 한다."""

    def test_check_secret(self):
        for bad in ("", None, "dev-only-change-me", "change-me", "x" * 31):
            with self.assertRaises(RuntimeError, msg=repr(bad)):
                check_secret({"SECRET_KEY": bad})
        check_secret({"SECRET_KEY": "k" * 32})


class ProxyFixTest(unittest.TestCase):
    """4. 프록시 뒤에서는 X-Forwarded-For 가 접속 주소가 되고, 설정이 0이면 무시한다."""

    def ip(self, hops):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:   # Windows: 닫힌 뒤에도 WAL 파일이 잠시 잡혀 있을 수 있다
            app = tmp_app(d, TRUSTED_PROXY_HOPS=hops)
            app.add_url_rule("/_ip", "ip", lambda: request.remote_addr or "")
            return app.test_client().get("/_ip", headers={"X-Forwarded-For": "203.0.113.7"},
                                         environ_base={"REMOTE_ADDR": "10.0.0.1"}).get_data(as_text=True)

    def test_hops(self):
        self.assertEqual(self.ip(1), "203.0.113.7")
        self.assertEqual(self.ip(0), "10.0.0.1")


class SearchLogTest(unittest.TestCase):
    """5. 결과가 없는 문구는 화면이 결과 수를 부풀려 보내도 '많이 찾는 검색어'에 오르지 않아야 한다."""

    def test_no_result_term_is_not_recorded(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:   # Windows: 닫힌 뒤에도 WAL 파일이 잠시 잡혀 있을 수 있다
            app = tmp_app(d)
            with app.app_context():
                from app.db import get_db
                add_ann(get_db(), "인공지능 바우처 지원사업 공고")
            c = app.test_client()
            for _ in range(2):
                c.post("/search-log", json={"q": "광고 문구 여기", "n": 99})
                c.post("/search-log", json={"q": "바우처", "n": 0})               # 화면 값이 0이어도 서버가 센다
            c.post("/search-log", json={"q": "바우처" + " " * 40, "n": 1})          # 40자 넘는 값은 버림
            from app.services import searches
            with app.app_context():
                from app.db import get_db
                top = searches.top_terms(get_db())
                rows = get_db().execute("SELECT term, results FROM search_logs").fetchall()
            self.assertEqual([t[0] for t in top], ["바우처"])
            self.assertEqual({(r[0], r[1]) for r in rows}, {("바우처", 1)})


if __name__ == "__main__":
    unittest.main()

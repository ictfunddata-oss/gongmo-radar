"""안전장치 — robots.txt 확인과, 공고 본문 속 지시문(프롬프트 인젝션) 방어를 확인한다."""
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from app.crawler import runner
from app.crawler.http import RunLog
from app.crawler.robots import RobotsGuard

SCHEMA = (Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text(encoding="utf-8")


class FakeResp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


class FakeSession:
    """주소 → 응답(FakeResp 또는 던질 예외). 요청 기록을 남긴다."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        r = self.table.get(url)
        if isinstance(r, Exception):
            raise r
        return r or FakeResp(404)


class FakeHttp:
    timeout = 5

    def __init__(self, table):
        self.s = FakeSession(table)
        self.robots = None

    def pause(self):
        pass


def guard_for(table, enabled=True):
    return RobotsGuard(FakeHttp(table), RunLog(echo=False), enabled)


SITE = "https://example.go.kr"


class RobotsTest(unittest.TestCase):
    def test_allows_when_star_rules_do_not_match(self):
        g = guard_for({SITE + "/robots.txt": FakeResp(200, "User-agent: *\nDisallow: /admin\n")})
        self.assertTrue(g.allowed(SITE + "/notices?page=1"))
        self.assertFalse(g.allowed(SITE + "/admin/x"))

    def test_rules_for_other_bots_do_not_apply(self):
        # NIA처럼 Googlebot 에만 막는 경로는 '*' 규칙(전체 허용)을 따르는 우리에게 해당하지 않는다
        text = "User-agent: *\nAllow: /\n\nUser-agent : Googlebot\nDisallow: /site/nia_kor/ex/bbs/\n"
        g = guard_for({"https://nia.test/robots.txt": FakeResp(200, text)})
        self.assertTrue(g.allowed("https://nia.test/site/nia_kor/ex/bbs/List.do"))

    def test_blocks_when_star_disallows_everything(self):
        g = guard_for({SITE + "/robots.txt": FakeResp(200, "User-agent: *\nDisallow: /\n")})
        self.assertFalse(g.allowed(SITE + "/notices"))

    def test_missing_robots_means_no_restriction(self):
        self.assertTrue(guard_for({SITE + "/robots.txt": FakeResp(404)}).allowed(SITE + "/notices"))

    def test_html_error_page_with_200_is_read_as_no_rules(self):
        # RAPA처럼 없는 경로에 HTML 쪽을 200으로 돌려주는 사이트
        html = "<!DOCTYPE html>\n<html lang=\"ko\">\n<head><title>페이지 없음</title></head><body>Disallow 라는 말이 본문에 있어도</body></html>"
        self.assertTrue(guard_for({SITE + "/robots.txt": FakeResp(200, html)}).allowed(SITE + "/notices"))

    def test_server_error_or_unreachable_blocks_the_run(self):
        self.assertFalse(guard_for({SITE + "/robots.txt": FakeResp(503)}).allowed(SITE + "/notices"))
        self.assertFalse(guard_for({SITE + "/robots.txt": ConnectionError("down")}).allowed(SITE + "/notices"))

    def test_disabled_check_always_allows_and_makes_no_request(self):
        g = guard_for({}, enabled=False)
        self.assertTrue(g.allowed(SITE + "/anything"))
        self.assertEqual(g.http.s.calls, [])

    def test_robots_is_fetched_once_per_site(self):
        g = guard_for({SITE + "/robots.txt": FakeResp(200, "User-agent: *\nAllow: /\n")})
        for i in range(3):
            g.allowed(f"{SITE}/n/{i}")
        self.assertEqual(len(g.http.s.calls), 1)


class CrawlBlockedTest(unittest.TestCase):
    def test_crawl_stops_before_any_request_when_robots_blocks(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        table = {}

        class Http(FakeHttp):
            def __init__(self, log, delay=0, **kw):
                super().__init__(table)
                table["https://www.nipa.kr/robots.txt"] = FakeResp(200, "User-agent: *\nDisallow: /\n")

            def get(self, url, **kw):          # 목록·상세 요청이 나가면 안 된다
                raise AssertionError("robots.txt 가 막았는데 요청을 보냄: " + url)

        cfg = {"CRAWL_DELAY": 0, "DOWNLOAD_ATTACHMENTS": False, "ATTACHMENT_DIR": "x", "ATTACH_MAX_MB": 1, "ROBOTS_CHECK": True}
        with mock.patch.object(runner, "HttpClient", Http):
            res = runner.crawl(conn, cfg, "nipa_business", mode="full", pages=1, echo=False)
        self.assertEqual((res["rows"], res["new"], res["errors"]), (0, 0, 1))
        self.assertEqual(res["status"], "오류")

"""NIPA 어댑터 파싱 테스트 — 저장해 둔 HTML 스냅샷으로 네트워크 없이 확인한다.

    python -m unittest discover tests
사이트가 개편되면 스냅샷을 새로 받아 기대값을 확인하고 고친다.
"""
import unittest
from pathlib import Path

from app.crawler.adapters.nipa import NipaBusinessAdapter
from app.crawler.attachments import filename_from_disposition
from app.crawler.utils import parse_period, safe_filename, size_to_bytes

FIX = Path(__file__).parent / "fixtures"


class NipaParseTest(unittest.TestCase):
    def setUp(self):
        self.ad = NipaBusinessAdapter(http=None)

    def test_list(self):
        rows, last = self.ad.parse_list((FIX / "nipa_list.html").read_text(encoding="utf-8"), 1)
        self.assertGreater(len(rows), 0)
        self.assertGreaterEqual(last, 1)
        for r in rows:
            self.assertTrue(r["post_no"].isdigit())
            self.assertTrue(r["title"])

    def test_detail(self):
        d = self.ad.parse_detail((FIX / "nipa_detail.html").read_text(encoding="utf-8"))
        self.assertTrue(d["posted_at"])
        self.assertIsInstance(d["files"], list)
        for f in d["files"]:
            self.assertTrue(f["url"].startswith("https://www.nipa.kr/comm/getFile"))
            self.assertEqual(f["seq"], d["files"].index(f) + 1)


class UtilTest(unittest.TestCase):
    def test_parse_period(self):
        self.assertEqual(parse_period("2026-10-01 09:00 ~ 2026-10-30 13:00"), ("2026-10-01T09:00", "2026-10-30T13:00"))
        self.assertEqual(parse_period("상시모집"), (None, None))

    def test_size(self):
        self.assertEqual(size_to_bytes("2 MB"), 2 * 1024 * 1024)
        self.assertEqual(size_to_bytes(""), 0)

    def test_filename(self):
        h = "attachment; filename=\"a.hwp\";filename*= UTF-8''%EB%B6%99%EC%9E%841.%20%EA%B3%B5%EA%B3%A0.hwp"
        self.assertEqual(filename_from_disposition(h), "붙임1. 공고.hwp")
        self.assertEqual(safe_filename('a<b>:c?.hwp'), "a_b__c_.hwp")


class MaskTest(unittest.TestCase):
    def test_contacts(self):
        from app.services.mask import mask_contacts as m
        self.assertEqual(m("문의 a.b@nipa.kr / +84 24 7300 0674"), "문의 [이메일] / [전화번호]")
        for s in ("02-2132-1234", "010 1234 5678", "043-931-5555", "(02)2132-1234"):
            self.assertEqual(m(s), "[전화번호]", s)
        for s in ("과학기술정보통신부 공고 제 2026-0977 호", "2026. 09. 29.", "과제당 3억원, 2026-10-01"):
            self.assertEqual(m(s), s)


class StatusTest(unittest.TestCase):
    def test_status(self):
        from datetime import datetime
        from app.services.public import status
        now = datetime(2026, 10, 6, 12, 0)
        self.assertEqual(status("2026-10-01T09:00", "2026-10-10T23:00", "모집", "2026-10-01", now)["label"], "D-4")
        self.assertEqual(status("2026-10-01T09:00", "2026-10-30T13:00", "모집", "2026-10-01", now)["st"], "open")
        self.assertEqual(status("2026-10-20", "2026-10-30", "모집", "2026-10-01", now)["st"], "upcoming")
        self.assertEqual(status("2026-04-01", "2026-11-30", "[접수마감] 모집", "2026-04-01", now)["st"], "ended")
        self.assertEqual(status(None, None, "모집", "2023-01-01", now)["st"], "ended")
        self.assertEqual(status(None, None, "모집", "2026-09-01", now)["st"], "always")
        self.assertEqual(status("2026-10-01", "2026-10-06", "모집", "2026-10-01", now)["label"], "오늘 마감")


class NiaParseTest(unittest.TestCase):
    """NIA 입찰공고 어댑터 — 스냅샷 파싱만 확인한다(네트워크 사용 안 함)."""

    def setUp(self):
        from app.crawler.adapters.nia import NiaBidAdapter
        self.ad = NiaBidAdapter(http=None)

    def test_list(self):
        rows, last = self.ad.parse_list((FIX / "nia_list.html").read_text(encoding="utf-8"), 1)
        self.assertEqual(len(rows), 10)
        self.assertGreater(last, 5)          # 쪽 링크의 '맨 뒤로' 값까지 읽는다
        for r in rows:
            self.assertTrue(r["post_no"].isdigit())
            self.assertTrue(r["title"] and "new" not in r["title"].split()[-1:])
            self.assertRegex(r["list_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(rows[0]["post_no"], "30068")
        self.assertEqual(rows[0]["biz"], "조달입찰공고")

    def test_detail(self):
        d = self.ad.parse_detail((FIX / "nia_detail.html").read_text(encoding="utf-8"))
        self.assertEqual(d["posted_at"], "2026-10-14")
        self.assertGreater(d["views"], 0)
        self.assertTrue(d["body"])
        self.assertEqual([f["seq"] for f in d["files"]], [1, 2])
        self.assertTrue(all(f["url"].startswith("https://www.nia.or.kr/common/board/Download.do") for f in d["files"]))

    def test_urls(self):
        self.assertTrue(self.ad.list_page_url(3).endswith("cbIdx=78336&pageIndex=3"))
        self.assertIn("bcIdx=30068", self.ad.detail_url("30068"))


class NiaPeriodTest(unittest.TestCase):
    """NIA 본문에서 접수 기간을 뽑는 패턴 — 실제 본문 문구 기준."""

    def ex(self, body, posted="2026-06-01"):
        from app.crawler.adapters.nia import extract_period
        return extract_period(body, posted)

    def test_notice_table(self):   # 공고일정 표: 날짜의 끝에는 연도가 없다
        self.assertEqual(self.ex("구 분 공고기간 컨소시엄 구성 승인 날 짜 2026.8.12(수) ~ 9.11(금) ~ 9.10(목) 18:00 시한"),
                         "2026-08-12 ~ 2026-09-11")

    def test_label_with_time(self):
        self.assertEqual(self.ex("3. 공모일자 : 2026.06.03.(수) ~ 06.24.(수) 4. 총 협약기간"), "2026-06-03 ~ 2026-06-24")

    def test_bid_submit(self):
        self.assertEqual(self.ex("제안서ㆍ가격 전자입찰서 제출 시작일시: 2026/09/29 10:00 ○ 제안서ㆍ가격 전자입찰서 제출 마감일시: 2026/10/01 10:00 ○ 개찰"),
                         "2026-09-29 10:00 ~ 2026-10-01 10:00")

    def test_deadline_only_uses_posted_date(self):
        self.assertEqual(self.ex("바. 신청기간 : 공고일 ~ 2026.2.24.(화) 18:00 까지 사. 신청방법", "2026-02-03"),
                         "2026-02-03 ~ 2026-02-24 18:00")

    def test_year_rollover_and_missing(self):
        self.assertEqual(self.ex("공고기간 2026.12.20(월) ~ 1.5(화)"), "2026-12-20 ~ 2027-01-05")
        self.assertEqual(self.ex("자세한 일정은 첨부 공고문을 확인하세요."), "")

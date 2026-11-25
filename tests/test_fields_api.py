"""3단계 W-llm — 표준 필드 API 보완(fields/api.py, extract_v1). 실제 API는 부르지 않고 가짜 클라이언트로 확인한다."""
import json
import re
import unittest

from app.services.fields import api
from app.services.fields.model import Att, Doc
from tests.test_llm import CFG, FakeClient, mem, msg

ATT_TEXT = """# 2027년 지원사업 공고

## 1. 사업 개요
□ **사업목적** : 중소기업의 AI 도입 지원

| 구분 | 내용 |
|---|---|
| 지원대상 | 국내 중소기업 |

□ 접수기간 : 2026. 12. 1.(월) ~ 2026. 12. 15.(월) 18:00
문의: test@example.com
"""


def doc(**kw):
    atts = [Att(seq=1, name="참가신청서.hwp", ext="hwp", text="신청서 서식"), Att(seq=2, name="붙임1. 공고문.hwpx", ext="hwpx", text=ATT_TEXT),
            Att(seq=3, name="안내서.pdf", ext="pdf", text="안내 " * 10), Att(seq=4, name="빈.pdf", ext="pdf", text="")]
    base = dict(ann_id=1, board="nipa_business", cls="공모지원사업", sub="지원사업", title="2027 AI 바우처", biz="AI",
                period_raw="", start_at=None, end_at=None, body="본문 안내. 담당 02-123-4567", attachments=atts)
    base.update(kw)
    return Doc(**base)


def reply(*fields):
    return msg({"fields": [dict(zip(("field", "status", "source_id", "quote", "evidence"), f)) for f in fields]})


class BuildInputTest(unittest.TestCase):
    def test_input(self):
        text = api.build_input(doc(), ["title", "qualify", "period"])
        notice = json.loads(re.search(r"<notice>(.*)</notice>", text).group(1))
        self.assertEqual(notice["missing"], ["qualify", "period"])            # title은 보내지 않는다
        self.assertEqual((notice["class"], notice["sub"]), ("공모지원사업", "지원사업"))
        self.assertNotIn("writer", notice)
        ids = re.findall(r'<source id="([^"]+)"', text)
        self.assertEqual(ids, ["body", "att:2", "att:3"])                      # 공고문 먼저, 서식은 뒤로, 최대 2개
        self.assertIn('name="붙임1. 공고문.hwpx"', text)
        self.assertNotIn("4567", text)
        self.assertNotIn("test@example.com", text)

    def test_limits(self):
        d = doc(body="가나 " * 7000, attachments=[Att(seq=2, name="공고문.hwp", ext="hwp", text="나다 " * 20000)])
        src = api.sources(d)
        self.assertEqual([len(s[1]) for s in src], [8000, 12000])
        d = doc(body="", attachments=[Att(seq=i, name=f"공고문{i}.hwp", ext="hwp", text="다라 " * 7000) for i in (1, 2)])
        self.assertEqual(sum(len(s[1]) for s in api.sources(d)), 24000)


class SupplementTest(unittest.TestCase):
    def run_sup(self, *fields, missing=("content", "qualify", "area", "period")):
        c, fc = mem(1), FakeClient([reply(*fields)])
        return api.supplement(c, CFG, doc(), list(missing), client=fc), fc, c

    def test_quote_passes(self):
        got, fc, c = self.run_sup(
            ("content", "확인", "att:2", "□ 사업목적 : 중소기업의  AI 도입 지원", "□ 사업목적"),       # 공백·** 차이는 무시
            ("qualify", "확인", "att:2", "| 지원대상 | 국내 중소기업 |", ""),
            ("period", "확인", "att:2", "□ 접수기간 : 2026. 12. 1.(월) ~ 2026. 12. 15.(월) 18:00", "접수기간"),
            ("area", "미확인", "", "", ""))
        self.assertEqual(set(got), {"content", "qualify", "area", "period"})
        fv = got["content"]
        self.assertEqual((fv.status, fv.source, fv.source_ref, fv.method, fv.prompt_version, fv.evidence),
                         ("확인", "attachment", "붙임1. 공고문.hwpx", "api", "extract_v1", "□ 사업목적"))
        self.assertEqual(got["qualify"].evidence, "| 지원대상 | 국내 중소기업 |")
        p = got["period"]
        self.assertEqual((p.status, p.start_at, p.end_at), ("확인", "2026-12-01", "2026-12-15 18:00"))
        self.assertEqual((got["area"].status, got["area"].method), ("미확인", "api"))
        kw = fc.calls[0]
        self.assertEqual(kw["max_tokens"], 4000)
        self.assertIn("발췌기", kw["system"][0]["text"])
        self.assertEqual(kw["output_config"]["format"]["schema"]["properties"]["fields"]["items"]["required"],
                         ["field", "status", "source_id", "quote", "evidence"])
        self.assertEqual(c.execute("SELECT stage, items, outcome FROM llm_calls").fetchone()[:], ("extract", 1, "ok"))

    def test_quote_fails(self):
        got, _, _ = self.run_sup(
            ("content", "확인", "att:2", "중소기업의 AI 도입과 해외 진출 지원", ""),     # 원문에 없는 말(지어냄)
            ("qualify", "확인", "body", "| 지원대상 | 국내 중소기업 |", ""),            # 다른 출처
            ("period", "확인", "att:9", "접수기간", ""),                               # 없는 출처
            ("title", "확인", "body", "본문 안내", ""),                                 # missing에 없는 칸
            missing=("content", "qualify", "period"))
        self.assertEqual(set(got), {"content", "qualify", "period"})
        for f in ("content", "qualify", "period"):
            self.assertEqual((got[f].status, got[f].note, got[f].value), ("미확인", "인용 불일치", None))

    def test_period_without_dates(self):
        got, _, _ = self.run_sup(("period", "확인", "body", "본문 안내.", ""), missing=("period",))
        self.assertEqual((got["period"].status, got["period"].start_at, got["period"].end_at), ("확인", None, None))

    def test_refusal_all_unknown(self):
        c, fc = mem(1), FakeClient([msg(stop="refusal")])
        got = api.supplement(c, CFG, doc(), ["content", "area"], client=fc)
        self.assertEqual({f: (v.status, v.note) for f, v in got.items()}, {"content": ("미확인", "API refusal"), "area": ("미확인", "API refusal")})

    def test_nothing_to_send(self):
        fc = FakeClient([])
        self.assertEqual(api.supplement(mem(1), CFG, doc(), ["title"], client=fc), {})
        self.assertEqual(fc.calls, [])

    def test_quote_in(self):
        self.assertTrue(api.quote_in("가 나\n다", "**가나**   다 라"))
        self.assertTrue(api.quote_in("지원대상 국내", "<td>지원대상</td><td>국내</td>"))
        self.assertFalse(api.quote_in("", "가나다"))
        self.assertFalse(api.quote_in("가다", "가나다"))


if __name__ == "__main__":
    unittest.main()

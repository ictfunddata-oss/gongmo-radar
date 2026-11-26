"""표준 필드 규칙 추출(app/services/fields/rules·sections·period, 00 부록 C) — 네트워크·DB 없이 원문 조각으로 검사한다.

조각(tests/fixtures/fields/)은 data/validation/gold-src 의 kordoc 결과·본문에서 연락처가 없는 부분만 잘라 옮겼다.
- kca_bid_overview.md: KCA 6239644 입찰공고문(hwp) — 청렴계약 표, '1. 입찰개요' HTML 표, '2. 입찰참가자격'
- nipa_notice.md: NIPA 17006 공고문(hwpx) 1~6장
- nipa_form_tail.md: 같은 공고문 끝의 '붙임1 … 신청 양식' 머리와 서식 표(맨 아래 '지원분야' 행 하나는 검사용으로 덧붙임)
- nia_body.txt: NIA 30211 본문(줄바꿈 없이 이어진 글) '1. 입찰에 부치는 사항' 부분
- nia_rfp_toc.md: NIA 30210 제안요청서 목차 + 'Ⅰ 사업 개요'
- nipa_16931_body.txt: NIPA 16931 본문(모집 기간이 사이트 기간과 다름)
"""
import unittest
from pathlib import Path

from app.services.fields import period, rules, sections
from app.services.fields.model import FIELDS, Att, Doc, FieldValue

FX = Path(__file__).resolve().parent / "fixtures" / "fields"


def fx(name):
    return (FX / name).read_text(encoding="utf-8")


def doc(**kw):
    base = dict(ann_id=1, board="nipa_business", cls="공모지원사업", sub=None, title="제목", biz="", period_raw="", start_at=None,
                end_at=None, body="", attachments=[])
    base.update(kw)
    return Doc(**base)


class NormalizeTest(unittest.TestCase):
    def test_html_table_to_rows(self):
        t = sections.normalize('<table>\n<tr><td>사업예산<br>(VAT포함)</td><td>금96,619,120원</td><td></td></tr>\n</table>')
        self.assertEqual(t, "사업예산 (VAT포함) | 금96,619,120원")

    def test_markdown_marks(self):
        t = sections.normalize("**1. 사업목적** \n\n| 구분 | 분류 |\n| --- | --- |\n- ○ **(목적)** 베타 \\~ 정식\n![image](a.png)\n### □ 추진 배경")
        self.assertEqual(t.split("\n"), ["1. 사업목적", "구분 | 분류", "○ (목적) 베타 ~ 정식", "□ 추진 배경"])

    def test_split_flat_body(self):
        t = sections.split_flat("안내 1. 일반사항 가. 공 모 명 : 사업 나. 기간 : 2026. 8. 12. ~ 9. 11. ○ 신청 ※ 참고")
        self.assertEqual(t.split("\n"), ["안내", "1. 일반사항", "가. 공 모 명 : 사업", "나. 기간 : 2026. 8. 12. ~ 9. 11.", "○ 신청", "※ 참고"])


class SectionTest(unittest.TestCase):
    def find(self, text, labels):
        return sections.find(sections.normalize(text), sections.label_re(labels))

    def test_nipa_notice_sections(self):
        t = fx("nipa_notice.md")
        sec = self.find(t, rules.SUPPORT["qualify"])
        self.assertEqual(sec.head, "3. 지원대상(신청자격) 및 비용")
        self.assertTrue(sec.value.startswith("○ (지원대상) 아래 조건에 부합하는 산업계, 학계, 연구계"))
        self.assertIn("산업계 | 중소기업, 스타트업", sec.value)
        self.assertNotIn("4. 평가 및 선정", sec.value)                # 같은 수준의 다음 머리에서 끝난다
        content = self.find(t, rules.SUPPORT["content"])
        self.assertEqual(content.head, "1. 사업목적")
        self.assertIn("‘26년 신규 확보한 첨단 GPU(B300)의 베타서비스를 통해", content.value)

    def test_kv_head_value(self):
        sec = self.find("□ (신청자격) 시설관리기관(컨소시엄 가능)\n- ※ 터널 우선\n□ (문의처) 담당부서", ["신청자격"])
        self.assertEqual(sec.value, "시설관리기관(컨소시엄 가능)\n※ 터널 우선")

    def test_toc_lines_skipped(self):
        t = sections.normalize(fx("nia_rfp_toc.md"))
        self.assertTrue(sections.is_toc("2. 입찰참가자격 3. 제안 평가 관련 사항"))
        self.assertTrue(sections.is_toc("Ⅰ. 사업 개요 ··········· 1"))
        sec = sections.find(t, sections.label_re(["사업개요"]))
        self.assertEqual(sec.head, "Ⅰ 사업 개요")                       # 목차의 'Ⅰ. 사업 개요 1'이 아니라 본문 머리
        self.assertTrue(sec.value.startswith("□ 사 업 명 : 2027년 디지털서비스플랫폼 운영"))
        self.assertIsNone(sections.find(t, sections.label_re(["입찰참가자격"])))   # 목차에만 있는 라벨

    def test_label_inside_sentence_is_not_head(self):
        t = "▸ 계약담당자는 제출서류(입찰보증금, 입찰참가자격 포함)에 대한 적정성 여부를 판정할 수 있습니다.\n★ 유의\n◐ 입찰참가자격(모두를 만족하여야 함)\n① 조달청 등록 업체"
        sec = self.find(t, ["입찰참가자격"])
        self.assertEqual(sec.head, "◐ 입찰참가자격(모두를 만족하여야 함)")
        self.assertEqual(sec.value, "① 조달청 등록 업체")

    def test_integrity_pledge_dropped(self):
        t = sections.normalize(fx("kca_bid_overview.md"))
        lines = sections.body_lines(t)
        self.assertFalse(any("청렴계약" in ln for ln in lines))
        self.assertTrue(any(ln.startswith("입찰건명 |") for ln in lines))

    def test_form_tail_cut(self):
        t = fx("nipa_notice.md") + "\n\n" + fx("nipa_form_tail.md")
        self.assertIn("지원분야 |", sections.normalize(t))
        self.assertIsNone(self.find(t, rules.SUPPORT["area"]))         # 붙임 서식 머리 아래는 읽지 않는다

    def test_table_row_contact_rejected(self):
        self.assertIsNone(self.find("사업내용 | 글로벌협력팀 | 043-931-5511", ["사업내용"]))


class PeriodTest(unittest.TestCase):
    def test_two_digit_year(self):
        start, end, ev = period.find(sections.normalize(fx("nipa_notice.md")))
        self.assertEqual((start, end), ("2026-11-19", "2026-11-24T15:00"))
        self.assertIn("(공고기간)", ev)
        self.assertEqual(period.parse_range("`26. 8. 12 ~ `26. 9. 2"), ("2026-08-12", "2026-09-02"))
        self.assertEqual(period.parse_range("‘26.09.15 ~ 09.30"), ("2026-09-15", "2026-09-30"))

    def test_forms(self):
        self.assertEqual(period.parse_range("2026. 9. 1.(월)부터 9. 30.(화) 18시까지"), ("2026-09-01", "2026-09-30T18:00"))
        self.assertEqual(period.parse_range("’26.11.17(화)~19(목)"), ("2026-11-17", "2026-11-19"))
        self.assertEqual(period.parse_range("2026. 12. 20. ~ 1. 5."), ("2026-12-20", "2027-01-05"))
        self.assertEqual(period.parse_range("2026. 3. 2. ~ 3. 20. 24:00"), ("2026-03-02", "2026-03-20T23:59"))
        row = "4 | 입찰서제출 | 전자입찰 | 2026/11/18 10:00:00 | 2026/11/20 10:00:00 | 나라장터"
        self.assertEqual(period.find(row)[:2], ("2026-11-18T10:00", "2026-11-20T10:00"))
        self.assertEqual(period.find("○ 접수마감 :2026년 9월 30일(수) 18시까지")[:2], (None, "2026-09-30T18:00"))

    def test_label_priority_and_other_periods(self):
        # 기존 extract_period가 못 읽는 두 자리 연도 → 보강 파서의 라벨 우선순위(접수기간 > 공고기간)
        t = "□ (사업기간) ’26. 1. 1. ~ ’26. 12. 31.\n○ (공고기간) ’26. 3. 2. ~ ’26. 3. 20.\n○ (접수기간) ’26. 3. 9. ~ ’26. 3. 20. 18:00"
        self.assertEqual(period.find(t)[:2], ("2026-03-09", "2026-03-20T18:00"))
        # 기존 extract_period가 읽으면 그 결과를 쓴다(부록 C.5 2: 먼저 extract_period)
        self.assertEqual(period.find("○ 공고기간 : 2026. 3. 2. ~ 3. 20.\n○ 접수기간 : 2026. 3. 9. ~ 3. 20.")[:2], ("2026-03-02", "2026-03-20"))
        self.assertIsNone(period.find("□ 사업기간 : 2026. 1. 1. ~ 2026. 12. 31."))

    def test_integrity_sentence_ignored(self):
        t = "입찰자는 반드시 입찰서 제출 시 아래 청렴계약서에 관한 내용을 숙지 2026. 1. 1. ~ 2026. 1. 5. 접수기간"
        self.assertIsNone(period.find(t))


class ExtractTest(unittest.TestCase):
    def test_kca_bid_overview(self):
        d = doc(board="kca_bidding", cls="입찰공고", title="(입찰공고) 2026년도 검사업무용 측정장비 부대품 구매", biz="전파검사",
                body="동 입찰공고 건은 조달청 국가종합전자조달사이트에 병행 공고하고 있으며",
                attachments=[Att(1, "20261109_입찰공고문.pdf", "pdf", "뒤섞인 글자 사업개요 : 틀린 값", "legacy"),
                             Att(2, "20261109_입찰공고문.hwp", "hwp", fx("kca_bid_overview.md"), "kordoc")])
        out = rules.extract(d)
        self.assertEqual(list(out), list(FIELDS))
        self.assertTrue(all(isinstance(v, FieldValue) and v.method == "rule" for v in out.values()))
        self.assertEqual(out["title"].value, "2026년도 검사업무용 측정장비 부대품 구매")
        c = out["content"]
        self.assertEqual((c.status, c.source, c.source_ref), ("확인", "attachment", "20261109_입찰공고문.hwp"))   # 같은 이름의 pdf보다 hwp
        self.assertEqual(c.value, "입찰건명: 2026년도 검사업무용 측정장비 부대품 구매\n계약기간: 계약체결일로부터 90일\n"
                                  "사업예산 (VAT포함): 금96,619,120원")
        p = out["period"]
        self.assertEqual((p.status, p.start_at, p.end_at), ("확인", "2026-11-09T18:00", "2026-11-17T10:00"))
        a = out["area"]
        self.assertEqual((a.value, a.note), ("분류: 전파검사\n계약방법: 전자투찰/적격심사", "대체값"))
        q = out["qualify"]
        self.assertEqual(q.evidence, "2. 입찰참가자격")
        self.assertIn("경쟁입찰 참가자격을 갖추어야하며", q.value)

    def test_nia_body(self):
        d = doc(board="nia_bid", cls="입찰공고", title="[입찰공고] 2027년 디지털정부 전시체험관 운영 및 관리", biz="입찰공고",
                body=fx("nia_body.txt"), start_at="2026-11-19", end_at="2026-12-01", period_raw="2026-11-19 ~ 2026-12-01")
        out = rules.extract(d)
        self.assertEqual(out["content"].value, "입찰명: 2027년 디지털정부 전시체험관 운영 및 관리\n계약기간: 2027. 1. 1 ~ 2027. 12. 31.\n"
                                               "사업예산: 99,876,834원(부가세 포함)")
        self.assertEqual(out["content"].source, "body")
        self.assertEqual(out["qualify"].evidence, "◐ 입찰참가자격(모두를 만족하여야 함)")
        self.assertTrue(out["qualify"].value.startswith("① 「국가를 당사자로 하는 계약에 관한 법률」 시행령 제12조"))
        self.assertNotIn("낙찰자 선정 방법", out["qualify"].value)
        self.assertEqual(out["area"].value, "계약방법: 제한경쟁(총액), 협상에 의한 계약, 전자입찰, 공동수급 허용, 하도급 불허")  # '입찰공고' 말머리는 뺀다
        self.assertEqual((out["period"].status, out["period"].source), ("확인", "site"))

    def test_period_conflict(self):
        d = doc(title="2026 인도 BTS(Bengaluru Tech Summit) 전시회 참가 기업 모집", body=fx("nipa_16931_body.txt"),
                start_at="2026-09-11T16:52", end_at="2026-09-30T23:00", period_raw="2026-09-11 16:52 ~ 2026-09-30 23:00")
        p = rules.extract(d)["period"]
        self.assertEqual((p.status, p.source, p.start_at, p.end_at), ("충돌", "site", "2026-09-11T16:52", "2026-09-30T23:00"))
        self.assertEqual(p.value, "2026-09-11 16:52 ~ 2026-09-30 23:00")
        self.assertIn("본문: ○ 모집 기간 : ‘26.09.15 ~ 09.30", p.note)

    def test_same_dates_no_conflict(self):
        d = doc(attachments=[Att(1, "공고문.hwpx", "hwpx", fx("nipa_notice.md"))],
                start_at="2026-11-19T11:00", end_at="2026-11-24T15:00", period_raw="2026-11-19 11:00 ~ 2026-11-24 15:00")
        self.assertEqual(rules.extract(d)["period"].status, "확인")

    def test_attachment_period_when_no_site(self):
        d = doc(attachments=[Att(1, "공고문.hwpx", "hwpx", fx("nipa_notice.md"))])
        p = rules.extract(d)["period"]
        self.assertEqual((p.status, p.source, p.source_ref, p.start_at, p.end_at),
                         ("확인", "attachment", "공고문.hwpx", "2026-11-19", "2026-11-24T15:00"))
        self.assertEqual(p.value, "2026-11-19 ~ 2026-11-24 15:00")

    def test_other_type_not_applicable(self):
        d = doc(cls="기타", title="[행사 안내] 2026 대한민국전파산업대전 개최", attachments=[Att(1, "공고문.hwpx", "hwpx", fx("nipa_notice.md"))])
        out = rules.extract(d)
        for f in ("qualify", "area", "period"):
            self.assertEqual((out[f].status, out[f].value, out[f].source), ("해당 없음", None, None))
        self.assertEqual(out["title"].value, "2026 대한민국전파산업대전 개최")
        self.assertEqual(out["content"].status, "확인")

    def test_unclassified_uses_support_labels_and_missing(self):
        out = rules.extract(doc(cls=None, body="짧은 본문"))
        self.assertEqual({f: out[f].status for f in FIELDS},
                         {"title": "확인", "content": "미확인", "qualify": "미확인", "area": "미확인", "period": "미확인"})

    def test_source_order_body_then_attachment(self):
        body = "□ 사업개요 ○ 본문에 적힌 사업 개요 문장입니다. " + "가" * 200
        att = Att(1, "공고문.hwp", "hwp", "1. 사업개요\n○ 첨부에 적힌 개요")
        self.assertEqual(rules.extract(doc(body=body, attachments=[att]))["content"].source, "body")
        short = rules.extract(doc(body="□ 사업개요 ○ 짧은 본문", attachments=[att]))["content"]   # 200자 미만 본문은 구획을 찾지 않는다
        self.assertEqual((short.source, short.value), ("attachment", "○ 첨부에 적힌 개요"))

    def test_form_and_zip_attachments(self):
        zip_text = "### 붙임2. 참가신청서.hwp\n1. 지원대상\n○ 서식 안의 글\n\n### 붙임1. 모집 공고문.hwp\n1. 지원대상\n○ 중소기업"
        d = doc(attachments=[Att(1, "붙임3. 참가신청서.hwp", "hwp", "1. 지원대상\n○ 신청서 안의 글"), Att(2, "공고.zip", "zip", zip_text)])
        q = rules.extract(d)["qualify"]
        self.assertEqual((q.value, q.source_ref), ("○ 중소기업", "공고.zip/붙임1. 모집 공고문.hwp"))

    def test_title_prefixes_and_contacts_masked(self):
        d = doc(title="[조달입찰공고] (사전규격 공개) 범정부 시스템 운영",
                attachments=[Att(1, "공고문.hwp", "hwp", "1. 지원대상\n○ 중소기업(문의 02-1234-5678, a@b.kr)")])
        out = rules.extract(d)
        self.assertEqual(out["title"].value, "범정부 시스템 운영")
        self.assertEqual(out["qualify"].value, "○ 중소기업(문의 [전화번호], [이메일])")

    def test_limits(self):
        att = Att(1, "공고문.hwp", "hwp", "1. 지원대상\n" + "\n".join("○ 대상 " + "가" * 80 for _ in range(60)))
        v = rules.extract(doc(attachments=[att]))["qualify"]
        self.assertLessEqual(len(v.value), rules.VALUE_MAX)
        self.assertLessEqual(v.value.count("\n") + 1, sections.MAX_LINES)


if __name__ == "__main__":
    unittest.main()

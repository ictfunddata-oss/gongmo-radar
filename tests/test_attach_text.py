"""첨부 글자 추출·정보 부족 공고의 첨부 판독(attach_text)·AI 입력에 첨부 포함 시험."""
import sqlite3
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from app.db import init_schema
from app.services import attach_text, extract

CFG = {"ATTACH_TEXT_MIN_BODY": 200, "ATTACH_TEXT_FILES": 3}


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    c.execute("INSERT INTO orgs(code, name, kind) VALUES ('o','기관','전담기관')")
    c.execute("INSERT INTO boards(org_id, code, name) VALUES (1,'b','게시판')")
    c.commit()
    return c


def ann(c, aid, body="", title="공고"):
    c.execute("INSERT INTO announcements(ann_id, board_id, post_no, title, body, posted_at) VALUES (?,1,?,?,?, '2026-01-01')", (aid, str(aid), title, body))


def att(c, aid, seq, name, ext, **kw):
    c.execute("INSERT INTO attachments(ann_id, seq, name, ext) VALUES (?,?,?,?)", (aid, seq, name, ext))
    for k, v in kw.items():
        c.execute(f"UPDATE attachments SET {k}=? WHERE ann_id=? AND seq=?", (v, aid, seq))


def hwp_record(tag, payload):
    head = tag | (0 << 10) | (len(payload) << 20)
    return struct.pack("<I", head) + payload


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.p = Path(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def test_hwp_paragraph_text_skips_control_blocks(self):
        # '가나' + 확장 제어문자(코드 11 + 14바이트) + '다' + 문단 끝(13)
        payload = "가나".encode("utf-16-le") + struct.pack("<H", 11) + b"\x00" * 14 + "다".encode("utf-16-le") + struct.pack("<H", 13)
        stream = hwp_record(66, b"abcd") + hwp_record(67, payload)           # 66 은 글자 기록이 아님
        self.assertEqual(extract.hwp_para_texts(stream), ["가나다\n"])

    def test_surrogate_pairs_are_joined_and_text_is_storable(self):
        emoji = "\U0001F600"
        units = emoji.encode("utf-16-le")                                     # 서로게이트 쌍 2조각
        payload = "공고 안내 ".encode("utf-16-le") + units + " 끝 신청 자격 확인 문서입니다".encode("utf-16-le") + struct.pack("<H", 13)
        got = extract.hwp_para_texts(hwp_record(67, payload))[0]
        self.assertIn(emoji, got)
        got.encode("utf-8")                                                   # 예외 없이 저장 가능
        lone = extract._clean("앞" + chr(0xD83D) + "뒤" * 40)                 # 짝 없는 조각은 지운다
        lone.encode("utf-8")

    def test_hwpx_and_docx(self):
        hx = self.p / "a.hwpx"
        sec = ('<?xml version="1.0"?><hs:sec xmlns:hs="s" xmlns:hp="p"><hp:p><hp:run><hp:t>모집 공고 안내문입니다 </hp:t></hp:run></hp:p>'
               '<hp:p><hp:run><hp:t>신청 자격은 중소기업이며 지원 규모는 과제당 최대 3억원입니다</hp:t></hp:run></hp:p></hs:sec>')
        with zipfile.ZipFile(hx, "w") as z:
            z.writestr("Contents/section0.xml", sec)
        text, st = extract.extract_text(hx, "hwpx")
        self.assertEqual(st, "ok")
        self.assertIn("과제당 최대 3억원", text)
        dx = self.p / "a.docx"
        with zipfile.ZipFile(dx, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>워드로 만든 공고문 내용이 여기에 들어 있습니다. 신청 자격은 중소기업이고 접수 기간은 3월 한 달입니다</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(extract.extract_text(dx, "docx")[1], "ok")

    def test_format_comes_from_content_not_extension(self):
        hx = self.p / "wrong.hwp"            # 확장자는 hwp 지만 실제로는 hwpx(zip)
        with zipfile.ZipFile(hx, "w") as z:
            z.writestr("Contents/section0.xml", '<s xmlns:hp="p"><hp:p><hp:t>확장자가 틀려도 내용을 보고 읽어야 하는 공고문 본문입니다 감사</hp:t></hp:p></s>')
        self.assertEqual(extract.sniff(hx), "hwpx")
        self.assertEqual(extract.extract_text(hx, "hwp")[1], "ok")

    def test_bad_files_do_not_raise(self):
        junk = self.p / "x.pdf"
        junk.write_bytes(b"<html>not a pdf</html>")
        self.assertEqual(extract.extract_text(junk, "pdf")[1], "unsupported")
        broken = self.p / "y.pdf"
        broken.write_bytes(b"%PDF-1.4 broken")
        self.assertTrue(extract.extract_text(broken, "pdf")[1].startswith("error"))
        self.assertEqual(extract.extract_text(self.p / "none.hwp", "hwp")[1][:5], "error")

    def test_empty_when_almost_no_text(self):
        hx = self.p / "e.hwpx"
        with zipfile.ZipFile(hx, "w") as z:
            z.writestr("Contents/section0.xml", '<s xmlns:hp="p"><hp:p><hp:t>짧음</hp:t></hp:p></s>')
        self.assertEqual(extract.extract_text(hx, "hwpx")[1], "empty")

    def test_hwp_compressed_section_roundtrip(self):
        payload = "접수 마감은 2026년 3월 5일입니다 지원 자격 확인".encode("utf-16-le") + struct.pack("<H", 13)
        raw = hwp_record(67, payload)
        comp = zlib.compressobj(wbits=-15)
        packed = comp.compress(raw) + comp.flush()
        self.assertEqual(zlib.decompress(packed, -15), raw)                    # 압축 방식(raw deflate) 가정 확인
        self.assertIn("2026년 3월 5일", extract.hwp_para_texts(zlib.decompress(packed, -15))[0])


class PickFilesTest(unittest.TestCase):
    def test_prefers_notice_and_skips_forms(self):
        rows = [{"seq": 1, "name": "신청서 양식.hwp", "ext": "hwp"}, {"seq": 2, "name": "사업 공고문.pdf", "ext": "pdf"},
                {"seq": 3, "name": "포스터.jpg", "ext": "jpg"}, {"seq": 4, "name": "동의서.hwp", "ext": "hwp"}]
        got = attach_text.pick_files(rows, 3)
        self.assertEqual([r["seq"] for r in got], [2])

    def test_only_forms_still_picks_one(self):
        rows = [{"seq": 1, "name": "신청서.hwp", "ext": "hwp"}, {"seq": 2, "name": "동의서.hwp", "ext": "hwp"}]
        self.assertEqual(len(attach_text.pick_files(rows, 3)), 1)


class TargetsTest(unittest.TestCase):
    def test_targets_short_body_only(self):
        c = mem()
        ann(c, 1, body="", title="모집 공고")                       # 대상
        ann(c, 2, body="가" * 500)                                    # 본문이 충분 → 대상 아님
        ann(c, 3, body="짧음")                                         # 대상(첨부가 이미지뿐이라 읽을 파일 없음 → 제외)
        for a in (1, 2, 3):
            att(c, a, 1, "공고문.hwp" if a != 3 else "포스터.jpg", "hwp" if a != 3 else "jpg")
        c.commit()
        got = attach_text.targets(c, CFG)
        self.assertEqual(got, [1])

    def test_already_read_is_skipped_unless_redo(self):
        c = mem()
        ann(c, 1)
        att(c, 1, 1, "공고문.hwp", "hwp", text_status="ok")
        c.commit()
        self.assertEqual(attach_text.targets(c, CFG), [])
        self.assertEqual(attach_text.targets(c, CFG, redo=True), [1])

    def test_explicit_ids_ignore_body_length(self):
        c = mem()
        ann(c, 1, body="가" * 500)
        att(c, 1, 1, "공고문.hwp", "hwp")
        c.commit()
        self.assertEqual(attach_text.targets(c, CFG), [])
        self.assertEqual(attach_text.targets(c, CFG, ann_ids=[1]), [1])

    def test_limit_and_newest_first(self):
        c = mem()
        for i in (1, 2, 3):
            ann(c, i)
            att(c, i, 1, "공고문.hwp", "hwp")
        c.execute("UPDATE announcements SET posted_at='2026-02-01' WHERE ann_id=2")
        c.commit()
        self.assertEqual(attach_text.targets(c, CFG, limit=1), [2])


class MigrationTest(unittest.TestCase):
    def test_old_attachments_table_gets_new_columns(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE attachments (ann_id INTEGER, seq INTEGER, name TEXT, PRIMARY KEY (ann_id, seq))")
        c.commit()
        init_schema(c)
        cols = {r[1] for r in c.execute("PRAGMA table_info(attachments)")}
        self.assertTrue({"text_body", "text_status", "text_at"} <= cols)


if __name__ == "__main__":
    unittest.main()

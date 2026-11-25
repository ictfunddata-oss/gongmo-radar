"""kordoc CLI 래퍼와 read_text 의 기존 추출기 넘김 시험. 실제 kordoc 은 부르지 않는다(Popen 을 가짜로)."""
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from app.services import extract, kordoc

CFG = {"KORDOC_ENABLED": True, "KORDOC_CMD": "npx -y kordoc@4.24.59", "KORDOC_TIMEOUT": 5}
MD = "# 모집 공고\n\n| 구분 | 내용 |\n|---|---|\n| 지원 규모 | 과제당 최대 3억원 |\n"


class FakePopen:
    """communicate 결과를 정해 두는 가짜 프로세스. calls 에 받은 인자를 남긴다."""
    calls = []

    def __init__(self, out=b"", err=b"", code=0, hang=False):
        self.out, self.err, self.returncode, self.hang, self.pid = out, err, code, hang, 4321

    def __call__(self, args, **kw):
        FakePopen.calls.append((args, kw))
        return self

    def communicate(self, timeout=None):
        if self.hang:
            self.hang = False
            raise subprocess.TimeoutExpired("kordoc", timeout)
        return self.out, self.err


def hwpx(path, text):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", f'<s xmlns:hp="p"><hp:p><hp:t>{text}</hp:t></hp:p></s>')
    return path


class ToTextTest(unittest.TestCase):
    def setUp(self):
        FakePopen.calls = []

    def run_fake(self, **kw):
        fake = FakePopen(**kw)
        with mock.patch.object(kordoc.subprocess, "Popen", fake), mock.patch.object(kordoc, "_kill_tree") as kill:
            got = kordoc.to_text(Path("a.hwp"), CFG)
        return got, kill

    def test_success_returns_markdown_with_table(self):
        (text, st), _ = self.run_fake(out=MD.encode("utf-8"))
        self.assertEqual(st, "ok")
        self.assertIn("| 지원 규모 | 과제당 최대 3억원 |", text)
        args, kw = FakePopen.calls[0]
        self.assertEqual(args[1:], ["-y", "kordoc@4.24.59", "a.hwp"])
        self.assertNotIn("--ocr", args)
        self.assertTrue(kw["cwd"])

    def test_output_is_cut_at_max_chars(self):
        (text, st), _ = self.run_fake(out=("가" * (extract.MAX_CHARS + 100)).encode("utf-8"))
        self.assertEqual((st, len(text)), ("ok", extract.MAX_CHARS))

    def test_nonzero_exit_is_error(self):
        (text, st), _ = self.run_fake(err=b"warn\nError: unsupported file\n", code=1)
        self.assertIsNone(text)
        self.assertEqual(st, "error:Error: unsupported file")

    def test_timeout_kills_tree(self):
        (text, st), kill = self.run_fake(hang=True)
        self.assertEqual((text, st), (None, "timeout"))
        kill.assert_called_once()

    def test_short_output_is_empty(self):
        (text, st), _ = self.run_fake(out=b"  \n# a\n")
        self.assertEqual((text, st), (None, "empty"))

    def test_disabled_does_not_run(self):
        with mock.patch.object(kordoc.subprocess, "Popen") as p:
            self.assertEqual(kordoc.to_text(Path("a.hwp"), {**CFG, "KORDOC_ENABLED": False})[0], None)
        p.assert_not_called()

    def test_missing_command_is_error(self):
        with mock.patch.object(kordoc.subprocess, "Popen", side_effect=FileNotFoundError("npx")):
            self.assertTrue(kordoc.to_text(Path("a.hwp"), CFG)[1].startswith("error:FileNotFoundError"))


class ReadTextTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.f = hwpx(Path(self.d.name) / "a.hwpx", "기존 추출기로 읽히는 공고문 본문입니다. 신청 자격은 중소기업입니다")

    def tearDown(self):
        self.d.cleanup()

    def test_kordoc_first(self):
        with mock.patch.object(kordoc, "to_text", return_value=(MD, "ok")):
            self.assertEqual(extract.read_text(self.f, "hwpx", CFG), (MD, "ok", "kordoc"))

    def test_falls_back_to_legacy_on_failure(self):
        for st in ("error:exit 1", "timeout", "empty"):
            with mock.patch.object(kordoc, "to_text", return_value=(None, st)):
                text, status, engine = extract.read_text(self.f, "hwpx", CFG)
            self.assertEqual((status, engine), ("ok", "legacy"), st)
            self.assertIn("신청 자격은 중소기업", text)

    def test_disabled_or_unsupported_skips_kordoc(self):
        junk = Path(self.d.name) / "x.pdf"
        junk.write_bytes(b"<html>not a pdf</html>")
        with mock.patch.object(kordoc, "to_text") as t:
            self.assertEqual(extract.read_text(self.f, "hwpx", {**CFG, "KORDOC_ENABLED": False})[2], "legacy")
            self.assertEqual(extract.read_text(junk, "pdf", CFG)[1:], ("unsupported", "legacy"))
        t.assert_not_called()


if __name__ == "__main__":
    unittest.main()

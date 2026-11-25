"""3단계 W-llm — 유형 분류(classify). 실제 API는 부르지 않고 가짜 클라이언트로 확인한다."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from app.services import classify, labels
from tests.test_llm import CFG, MODEL, FakeClient, conn_error, mem, msg

ROOT = Path(__file__).resolve().parent.parent


def ids_of(kw):
    text = kw["messages"][0]["content"]
    return [x["ann_id"] for x in json.loads(re.search(r"<items>\n(.*)\n</items>", text, re.S).group(1))]


def r(i, cls="공모지원사업", sub="지원사업"):
    return {"ann_id": i, "class": cls, "sub": sub, "confidence": "high", "reason": f"근거 {i}"}


def answer(drop=(), bad=(), **kw):
    """요청에 든 공고를 모두 공모지원사업/지원사업으로 답한다. drop은 빼고, bad는 sub를 class에 맞지 않게."""
    def f(req):
        out = [r(i, sub="사전규격") if i in bad else r(i) for i in ids_of(req) if i not in drop]
        return msg({"results": out}, **kw)
    return f


def lab(c, i):
    return labels.get(c, i)


class BuildItemsTest(unittest.TestCase):
    def test_items_and_make_input(self):
        c = mem(2)
        c.execute("INSERT INTO attachments(ann_id, seq, name, ext) VALUES (1,1,'공고문.hwp','hwp')")
        items = classify.build_items(c, [2, 1, 99])
        self.assertEqual([x["ann_id"] for x in items], [2, 1])
        x = items[1]
        self.assertEqual(set(x), {"ann_id", "board", "post_no", "title", "biz", "site_status", "period", "posted", "body", "files"})
        self.assertEqual((x["board"], x["files"]), ("nia_bid", ["공고문.hwp"]))
        self.assertNotIn("4567", x["body"])                         # 연락처 가림
        self.assertEqual(classify.input_hash(x), classify.input_hash(dict(reversed(list(x.items())))))
        sys.path.insert(0, str(ROOT / "plan" / "validation"))
        try:
            import make_input
        finally:
            sys.path.remove(str(ROOT / "plan" / "validation"))
        self.assertEqual(list(make_input.items(c, "nia_bid")), classify.build_items(c, [1, 2]))


class RunTest(unittest.TestCase):
    def test_ok(self):
        c, fc = mem(3), FakeClient([answer(req="req_9")])
        st = classify.run(c, CFG, [1, 2, 3], client=fc)
        self.assertEqual((st["items"], st["calls"], st["확정"]), (3, 1, 3))
        row = lab(c, 2)
        self.assertEqual((row["class"], row["sub"], row["status"], row["source"], row["prompt_version"], row["model"], row["request_id"]),
                         ("공모지원사업", "지원사업", "확정", "api", "classify_v2", MODEL, "req_9"))
        self.assertEqual(row["input_hash"], classify.input_hash(classify.build_items(c, [2])[0]))
        self.assertEqual(ids_of(fc.calls[0]), [1, 2, 3])
        self.assertIn("<rules>", fc.calls[0]["system"][0]["text"])

    def test_missing_retried_once_then_manual(self):
        c, fc = mem(3), FakeClient([answer(drop={2, 3}), answer(drop={3})])
        st = classify.run(c, CFG, [1, 2, 3], client=fc)
        self.assertEqual(ids_of(fc.calls[1]), [2, 3])                # 빠진 것만 다시
        self.assertEqual(len(fc.calls), 2)                           # 한 번만
        self.assertEqual((lab(c, 2)["status"], lab(c, 3)["status"]), ("확정", "수동 확인"))
        self.assertIsNone(lab(c, 3)["class"])
        self.assertEqual((st["확정"], st["수동 확인"]), (2, 1))

    def test_bad_sub(self):
        c, fc = mem(2), FakeClient([answer(bad={1, 2}), answer(bad={2})])
        classify.run(c, CFG, [1, 2], client=fc)
        self.assertEqual(ids_of(fc.calls[1]), [1, 2])
        self.assertEqual((lab(c, 1)["status"], lab(c, 1)["sub"]), ("확정", "지원사업"))
        row = lab(c, 2)
        self.assertEqual((row["status"], row["class"], row["sub"]), ("수동 확인", "공모지원사업", None))

    def test_refusal_is_hold(self):
        c, fc = mem(2), FakeClient([msg(stop="refusal")])
        st = classify.run(c, CFG, [1, 2], client=fc)
        self.assertEqual(st["분류 보류"], 2)
        self.assertEqual((lab(c, 1)["status"], lab(c, 1)["class"]), ("분류 보류", None))
        self.assertEqual(labels.public_type(lab(c, 1)), "미분류")

    def test_max_tokens_splits(self):
        c, fc = mem(4), FakeClient([msg(stop="max_tokens"), answer(), msg(stop="max_tokens"), answer(), answer()])
        st = classify.run(c, CFG, [1, 2, 3, 4], client=fc)
        self.assertEqual([ids_of(k) for k in fc.calls], [[1, 2, 3, 4], [1, 2], [3, 4], [3], [4]])
        self.assertEqual(st["확정"], 4)
        self.assertEqual([x["outcome"] for x in c.execute("SELECT outcome FROM llm_calls ORDER BY call_id")],
                         ["max_tokens", "ok", "max_tokens", "ok", "ok"])

    def test_fallback_model_recorded(self):
        c, fc = mem(1), FakeClient([answer(fallback_to="claude-other-9")])
        classify.run(c, CFG, [1], client=fc)
        self.assertEqual(lab(c, 1)["model"], "claude-other-9")
        self.assertEqual(c.execute("SELECT fallback, served_model FROM llm_calls").fetchone()[:], (1, "claude-other-9"))

    def test_api_error_then_next_chunk(self):
        c, fc = mem(4), FakeClient([conn_error(), answer()])
        said = []
        with mock.patch.object(classify, "CHUNK", 2):
            st = classify.run(c, CFG, [1, 2, 3, 4], client=fc, say=said.append)
        self.assertEqual((st["errors"], st["확정"]), (1, 2))
        self.assertIsNone(lab(c, 1))
        self.assertEqual(lab(c, 3)["status"], "확정")
        self.assertEqual([x[0] for x in c.execute("SELECT outcome FROM llm_calls ORDER BY call_id")], ["error", "ok"])
        self.assertTrue(said)

    def test_manual_kept(self):
        c, fc = mem(2), FakeClient([answer()])
        labels.set_manual(c, 1, "입찰공고", "입찰", "admin")
        st = classify.run(c, CFG, [1, 2], client=fc)
        self.assertEqual(st["kept_manual"], 1)
        self.assertEqual((lab(c, 1)["class"], lab(c, 1)["source"]), ("입찰공고", "manual"))

    def test_no_key(self):
        with self.assertRaises(RuntimeError):
            classify.run(mem(1), {**CFG, "CLAUDE_API": ""}, [1])


class TargetsTest(unittest.TestCase):
    def test_same_hash_not_resent(self):
        c = mem(3)
        classify.run(c, CFG, [1, 2], client=FakeClient([answer()]))
        labels.set_manual(c, 3, "기타", "안내", "admin")
        self.assertEqual(classify.targets(c), [])
        self.assertEqual(sorted(classify.targets(c, redo=True)), [1, 2])          # manual은 redo여도 빼기
        c.execute("UPDATE announcements SET title='바뀐 제목' WHERE ann_id=1")
        self.assertEqual(classify.targets(c), [1])
        c.execute("DELETE FROM announcement_labels WHERE ann_id=2")
        self.assertEqual(classify.targets(c, limit=1), [2])                       # 게시일 최신순(2가 1보다 늦다)


class BatchTest(unittest.TestCase):
    def test_submit_and_collect(self):
        c = mem(4)
        fc = FakeClient()
        with mock.patch.object(classify, "CHUNK", 2):
            bid = classify.submit_batch(c, CFG, [1, 2, 3, 4], client=fc, say=lambda *_: None)
        self.assertEqual(bid, "msgbatch_1")
        reqs = fc.batch_reqs[0]
        self.assertEqual([q["custom_id"] for q in reqs], ["classify-001", "classify-002"])
        self.assertNotIn("fallbacks", reqs[0]["params"])
        self.assertEqual(json.loads(c.execute("SELECT value FROM app_kv WHERE key='llm_batches'").fetchone()[0])[0]["id"], bid)

        fc.batch = {"status": "in_progress"}
        self.assertEqual(classify.collect(c, CFG, client=fc)["pending"], 1)

        ok = NS(type="succeeded", message=msg({"results": [r(4, "입찰공고", "입찰"), r(3, "입찰공고", "입찰")]}))
        fc.batch = {"status": "ended", "results": [NS(custom_id="classify-002", result=ok),             # 순서가 섞여도 custom_id로 맞춘다
                                                   NS(custom_id="classify-001", result=NS(type="succeeded", message=msg(stop="refusal")))]}
        st = classify.collect(c, CFG, client=fc)
        self.assertEqual((st["batches"], st["pending"], st["확정"], st["분류 보류"]), (1, 0, 2, 2))
        self.assertEqual((lab(c, 3)["class"], lab(c, 3)["request_id"]), ("입찰공고", "batch:msgbatch_1"))
        self.assertEqual(lab(c, 1)["status"], "분류 보류")
        self.assertEqual(json.loads(c.execute("SELECT value FROM app_kv WHERE key='llm_batches'").fetchone()[0]), [])
        self.assertEqual({x[0] for x in c.execute("SELECT mode FROM llm_calls")}, {"batch"})


class ImportCliTest(unittest.TestCase):
    def test_import(self):
        c = mem(5)
        labels.set_manual(c, 5, "기타", "안내", "admin")
        items = classify.build_items(c, [1, 2, 3, 4, 5])
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "20261125-v2-low"
            (run / "in" / "nia_bid").mkdir(parents=True)
            (run / "out" / "nia_bid").mkdir(parents=True)
            (run / "meta.txt").write_text("model=claude-sonnet-5-5\neffort=low\nprompt=classify_v2\n", encoding="utf-8")
            def chunk(n, rows):
                (run / "in" / "nia_bid" / f"chunk-{n:02d}.jsonl").write_text(
                    "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
            chunk(1, items[:4])
            chunk(2, items[4:])
            out = {"type": "result", "is_error": False, "structured_output": {"results": [
                r(1, "입찰공고", "협상공모"), r(2, "기타", "입찰"), r(4, "기타", "채용")]}}       # 3 빠짐, 2는 sub 불일치
            (run / "out" / "nia_bid" / "chunk-01.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            (run / "out" / "nia_bid" / "chunk-02.json").write_text("{깨짐", encoding="utf-8")
            st = classify.import_cli(c, run)
        self.assertEqual((st["items"], st["확정"], st["수동 확인"], st["missing"], st["failed_chunks"]), (5, 2, 1, 2, 1))
        row = lab(c, 1)
        self.assertEqual((row["class"], row["sub"], row["request_id"], row["model"], row["prompt_version"], row["status"]),
                         ("입찰공고", "협상공모", "cli:20261125-v2-low", MODEL, "classify_v2", "확정"))
        self.assertEqual((lab(c, 2)["status"], lab(c, 2)["class"], lab(c, 2)["sub"]), ("수동 확인", "기타", None))
        self.assertIsNone(lab(c, 3))
        self.assertEqual(lab(c, 5)["source"], "manual")
        self.assertNotIn(1, classify.targets(c))                  # 가져온 라벨은 같은 입력이면 다시 보내지 않는다

    def test_real_run_dir_if_present(self):
        run = ROOT / "data" / "validation" / "20261125-v2-low"
        if not (run / "in").exists():
            self.skipTest("검증 실행 폴더 없음")
        c = mem(0)
        st = classify.import_cli(c, run)                         # 공고가 없는 DB: 모두 unknown, 형식만 읽힌다
        self.assertGreater(st["items"], 0)
        self.assertEqual(st["unknown"] + st["missing"], st["items"])
        self.assertEqual(st["failed_chunks"], 0)


if __name__ == "__main__":
    unittest.main()

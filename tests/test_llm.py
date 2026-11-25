"""3단계 W-llm — Claude API 호출(llm.call_json·일괄 처리·비용). 실제 API는 부르지 않고 가짜 클라이언트로 확인한다."""
import json
import sqlite3
import unittest
from types import SimpleNamespace as NS

import anthropic
import httpx2

from app.services import llm
from tests.helpers import SCHEMA

MODEL = "claude-sonnet-5-5"
CFG = {"CLAUDE_API": "test-key", "CLAUDE_MODEL": MODEL, "CLAUDE_MODEL_EFFORT": "low", "CLAUDE_FALLBACKS": True}


def mem(n=0, board="nia_bid"):
    """공고 n건(ann_id 1..n)이 든 메모리 DB."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
    c.execute("INSERT INTO orgs(code, name, kind) VALUES ('nia','기관','전담기관')")
    c.execute("INSERT INTO boards(org_id, code, name, list_url) VALUES (1,?,'게시판','http://x')", (board,))
    for i in range(1, n + 1):
        c.execute("INSERT INTO announcements(ann_id, board_id, post_no, title, biz, body, posted_at, first_seen, last_seen) "
                  "VALUES (?,1,?,?,'공모',?,?, '2026-11-01','2026-11-01')",
                  (i, str(100 + i), f"공고 {i}", f"본문 {i} 문의 담당자 02-123-4567", f"2026-11-{i % 28 + 1:02d}"))
    c.commit()
    return c


def usage(i=1000, o=200, cr=0, cw=0, iterations=None):
    return NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr, cache_creation_input_tokens=cw, iterations=iterations)


def msg(data=None, *, stop="end_turn", model=MODEL, fallback_to=None, req="req_1", text=None, u=None):
    """가짜 응답 메시지. fallback_to를 주면 content 앞에 fallback 블록이 섞이고 usage.iterations에 대체 기록이 남는다."""
    content = [] if stop in ("refusal", "max_tokens") and data is None else [NS(type="text", text=text if text is not None else json.dumps(data, ensure_ascii=False))]
    u = u or usage()
    if fallback_to:
        content.insert(0, NS(type="fallback", from_=NS(model=model), to=NS(model=fallback_to), trigger=NS(type="refusal")))
        u.iterations = [NS(type="message", model=model), NS(type="fallback_message", model=fallback_to)]
        model = fallback_to
    return NS(content=content, stop_reason=stop, model=model, usage=u, _request_id=req)


def conn_error():
    return anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.invalid/v1/messages"))


class FakeClient:
    """client.beta.messages.create 와 client.messages.batches.* 만 흉내 낸다. replies 원소: 응답·예외·함수(kw → 응답)."""

    def __init__(self, replies=(), batch=None):
        self.replies, self.calls, self.batch_reqs = list(replies), [], []
        self.batch = batch or {}                  # {"status": "ended", "results": [...]}
        self.beta = NS(messages=NS(create=self._create))
        self.messages = NS(batches=NS(create=self._b_create, retrieve=self._b_retrieve, results=self._b_results))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        r = r(kw) if callable(r) else r
        if isinstance(r, Exception):
            raise r
        return r

    def _b_create(self, *, requests):
        self.batch_reqs.append(requests)
        return NS(id=f"msgbatch_{len(self.batch_reqs)}")

    def _b_retrieve(self, batch_id):
        return NS(id=batch_id, processing_status=self.batch.get("status", "ended"))

    def _b_results(self, batch_id):
        return iter(self.batch.get("results", []))


def calls(c):
    return [dict(r) for r in c.execute("SELECT * FROM llm_calls ORDER BY call_id")]


SCHEMA_OBJ = {"type": "object"}


def call(c, client, cfg=CFG):
    return llm.call_json(c, cfg, stage="classify", system="SYS", user_text="USER", schema=SCHEMA_OBJ, max_tokens=8000, items=3,
                         client=client)


class CallJsonTest(unittest.TestCase):
    def test_make_client(self):
        with self.assertRaises(RuntimeError):
            llm.make_client({**CFG, "CLAUDE_API": ""})
        self.assertIsInstance(llm.make_client(CFG), anthropic.Anthropic)

    def test_ok_request_shape_and_record(self):
        c, fc = mem(), FakeClient([msg({"results": []}, u=usage(1000, 200, 500, 100))])
        res = call(c, fc)
        self.assertEqual((res.outcome, res.data, res.fallback, res.served_model, res.request_id), ("ok", {"results": []}, False, MODEL, "req_1"))
        kw = fc.calls[0]
        self.assertEqual(kw["model"], MODEL)
        self.assertEqual(kw["max_tokens"], 8000)
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["system"], [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(kw["messages"], [{"role": "user", "content": "USER"}])
        self.assertEqual(kw["output_config"], {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA_OBJ}})
        for k in ("temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(k, kw)
        row = calls(c)[0]
        self.assertEqual((row["stage"], row["mode"], row["outcome"], row["items"], row["fallback"], row["request_id"]),
                         ("classify", "sync", "ok", 3, 0, "req_1"))
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["cache_read_tokens"], row["cache_write_tokens"]), (1000, 200, 500, 100))
        self.assertAlmostEqual(row["cost_usd"], (1000 * 2 + 200 * 10 + 500 * 0.1 + 100 * 2.5) / 1e6)

    def test_fallbacks_off(self):
        c, fc = mem(), FakeClient([msg({})])
        call(c, fc, {**CFG, "CLAUDE_FALLBACKS": False})
        self.assertNotIn("fallbacks", fc.calls[0])
        self.assertNotIn("betas", fc.calls[0])

    def test_fallback_served(self):
        c, fc = mem(), FakeClient([msg({"results": [1]}, fallback_to="claude-other-9")])
        res = call(c, fc)
        self.assertEqual((res.outcome, res.data, res.fallback, res.served_model), ("ok", {"results": [1]}, True, "claude-other-9"))
        row = calls(c)[0]
        self.assertEqual((row["model"], row["served_model"], row["fallback"]), (MODEL, "claude-other-9", 1))
        self.assertIsNone(row["cost_usd"])                      # 단가표에 없는 모델

    def test_refusal_max_tokens_invalid(self):
        c, fc = mem(), FakeClient([msg(stop="refusal"), msg(stop="max_tokens"), msg(text="{잘린")])
        self.assertEqual([call(c, fc).outcome for _ in range(3)], ["refusal", "max_tokens", "invalid"])
        self.assertEqual([r["outcome"] for r in calls(c)], ["refusal", "max_tokens", "invalid"])

    def test_api_error_is_outcome(self):
        c, fc = mem(), FakeClient([conn_error()])
        res = call(c, fc)
        self.assertEqual(res.outcome, "error")
        row = calls(c)[0]
        self.assertEqual(row["outcome"], "error")
        self.assertIn("APIConnectionError", row["error"])

    def test_other_exception_propagates(self):
        c, fc = mem(), FakeClient([ValueError("버그")])
        with self.assertRaises(ValueError):
            call(c, fc)


class CostTest(unittest.TestCase):
    def test_cost(self):
        u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 1_000_000, "cache_write_tokens": 1_000_000}
        self.assertAlmostEqual(llm.cost(MODEL, u), 2.0 + 10.0 + 0.1 + 2.5)
        self.assertAlmostEqual(llm.cost(MODEL, u, batch=True), (2.0 + 10.0 + 0.1 + 2.5) / 2)
        self.assertAlmostEqual(llm.cost(MODEL, {"input_tokens": 3000, "output_tokens": 500}), 0.011)
        self.assertIsNone(llm.cost("claude-unknown", u))


class BatchTest(unittest.TestCase):
    def test_request_has_no_fallbacks(self):
        r = llm.batch_request(CFG, "c-1", system="S", user_text="U", schema=SCHEMA_OBJ, max_tokens=8000)
        self.assertEqual(r["custom_id"], "c-1")
        self.assertNotIn("fallbacks", r["params"])
        self.assertEqual(r["params"]["output_config"]["effort"], "low")

    def test_results_matched_by_custom_id(self):
        ok = lambda d: NS(type="succeeded", message=msg(d, req=None))
        fc = FakeClient(batch={"status": "ended", "results": [
            NS(custom_id="b", result=ok({"x": 2})),
            NS(custom_id="a", result=ok({"x": 1})),
            NS(custom_id="c", result=NS(type="errored", error=NS(error=NS(message="overloaded")))),
        ]})
        c = mem()
        got = llm.batch_results(c, CFG, "msgbatch_1", stage="classify", items={"a": 2, "b": 3}, client=fc)
        self.assertEqual((got["a"].data, got["b"].data, got["c"].outcome), ({"x": 1}, {"x": 2}, "error"))
        self.assertEqual(got["a"].request_id, "batch:msgbatch_1")
        rows = calls(c)
        self.assertEqual({r["mode"] for r in rows}, {"batch"})
        self.assertAlmostEqual(rows[0]["cost_usd"], (1000 * 2 + 200 * 10) / 1e6 / 2)   # 50%

    def test_not_ended(self):
        fc = FakeClient(batch={"status": "in_progress"})
        self.assertIsNone(llm.batch_results(mem(), CFG, "msgbatch_1", stage="classify", client=fc))


if __name__ == "__main__":
    unittest.main()

"""Claude API 호출(ADR-045·049, 00 부록 B.3) — 구조화 출력 JSON 한 번 부르기, 일괄 처리, llm_calls 기록, 비용 추정.

- 거절(refusal)·잘림(max_tokens)·JSON 아님(invalid)·API 오류(error)는 예외가 아니라 LLMResult.outcome 으로 돌려준다.
- 동기 호출은 서버 측 대체(fallbacks="default")를 쓴다(CLAUDE_FALLBACKS). 일괄 처리에는 넣지 않는다.
- 키는 cfg["CLAUDE_API"]만 쓴다(SDK 기본 환경 변수 ANTHROPIC_API_KEY에 기대지 않는다).
"""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime

import anthropic

# 백만 토큰당 USD(2026-11-24 기준). 표에 없는 모델(대체 모델 등)은 cost_usd를 NULL로 둔다
PRICES = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10, "cache_write": 2.50},
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
OUTCOMES = ("ok", "refusal", "max_tokens", "invalid", "error")


@dataclass
class LLMResult:
    data: object                     # 읽은 JSON(outcome=ok일 때만)
    outcome: str                     # ok / refusal / max_tokens / invalid / error
    model: str | None                # 요청한 모델
    served_model: str | None         # 응답한 모델(대체되면 대체 모델)
    fallback: bool = False
    request_id: str | None = None
    usage: dict = field(default_factory=dict)
    error: str | None = None
    cost_usd: float | None = None


def make_client(cfg):
    """API 클라이언트. 키가 없으면 RuntimeError(부르는 쪽이 '키 없음'으로 건너뛴다)."""
    key = (cfg.get("CLAUDE_API") or "").strip()
    if not key:
        raise RuntimeError("CLAUDE_API 키가 없습니다")
    return anthropic.Anthropic(api_key=key)


def _get(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _usage(u):
    return {"input_tokens": _get(u, "input_tokens") or 0, "output_tokens": _get(u, "output_tokens") or 0,
            "cache_read_tokens": _get(u, "cache_read_input_tokens") or 0, "cache_write_tokens": _get(u, "cache_creation_input_tokens") or 0}


def cost(model, usage, batch=False):
    """단가표로 계산한 추정 비용(USD). 모르는 모델이면 None. 일괄 처리는 50%."""
    p = PRICES.get(model or "")
    if p is None:
        return None
    usd = (usage.get("input_tokens", 0) * p["input"] + usage.get("output_tokens", 0) * p["output"]
           + usage.get("cache_read_tokens", 0) * p["cache_read"] + usage.get("cache_write_tokens", 0) * p["cache_write"]) / 1_000_000
    return round(usd * (0.5 if batch else 1), 6)


def read_message(resp, model, *, batch=False):
    """응답 메시지 → LLMResult. stop_reason을 먼저 보고, JSON은 type=='text' 블록에서만 읽는다(대체되면 fallback 블록이 섞인다)."""
    served = _get(resp, "model") or model
    u = _get(resp, "usage")
    iters = _get(u, "iterations") or []
    fb_iter = [it for it in iters if _get(it, "type") == "fallback_message"]
    if fb_iter and _get(fb_iter[-1], "model"):
        served = _get(fb_iter[-1], "model")
    fallback = bool(fb_iter) or served != model
    usage = _usage(u)
    res = LLMResult(data=None, outcome="ok", model=model, served_model=served, fallback=fallback,
                    request_id=_get(resp, "_request_id"), usage=usage, cost_usd=cost(served, usage, batch))
    stop = _get(resp, "stop_reason")
    if stop in ("refusal", "max_tokens"):
        res.outcome = stop
        return res
    text = "".join(_get(b, "text") or "" for b in (_get(resp, "content") or []) if _get(b, "type") == "text")
    try:
        res.data = json.loads(text)
    except ValueError as e:
        res.outcome, res.error = "invalid", f"JSON 아님: {e}"[:500]
    return res


def record(conn, res, *, stage, mode, items, started_at, ms, run_id=None):
    """llm_calls 에 한 줄 남기고 커밋한다(비용 실측, I-11)."""
    conn.execute(
        "INSERT INTO llm_calls (run_id, stage, mode, model, served_model, fallback, request_id, items, input_tokens, output_tokens, "
        "cache_read_tokens, cache_write_tokens, cost_usd, outcome, error, started_at, ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, stage, mode, res.model, res.served_model, int(res.fallback), res.request_id, items, res.usage.get("input_tokens"),
         res.usage.get("output_tokens"), res.usage.get("cache_read_tokens"), res.usage.get("cache_write_tokens"), res.cost_usd,
         res.outcome, res.error, started_at, ms))
    conn.commit()


def _params(cfg, *, system, user_text, schema, max_tokens):
    return {
        "model": cfg["CLAUDE_MODEL"],
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_text}],
        "output_config": {"effort": cfg["CLAUDE_MODEL_EFFORT"], "format": {"type": "json_schema", "schema": schema}},
    }


def call_json(conn, cfg, *, stage, system, user_text, schema, max_tokens, items, run_id=None, client=None):
    """동기 호출 한 번 → LLMResult. 결과마다 llm_calls 를 기록한다. 재시도는 SDK 기본(2회)만."""
    client = client or make_client(cfg)
    model = cfg["CLAUDE_MODEL"]
    kw = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if cfg.get("CLAUDE_FALLBACKS") else {}
    started, t0 = datetime.now().isoformat(timespec="seconds"), time.monotonic()
    try:
        resp = client.beta.messages.create(**_params(cfg, system=system, user_text=user_text, schema=schema, max_tokens=max_tokens), **kw)
        res = read_message(resp, model)
    except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        res = LLMResult(data=None, outcome="error", model=model, served_model=None, request_id=getattr(e, "request_id", None),
                        error=f"{type(e).__name__}: {e}"[:500])
    record(conn, res, stage=stage, mode="sync", items=items, started_at=started, ms=int((time.monotonic() - t0) * 1000), run_id=run_id)
    return res


def batch_request(cfg, custom_id, *, system, user_text, schema, max_tokens):
    """일괄 처리 요청 한 건. fallbacks는 넣지 않는다(ADR-049: 일괄 처리에서 거절되면 분류 보류)."""
    return {"custom_id": custom_id, "params": _params(cfg, system=system, user_text=user_text, schema=schema, max_tokens=max_tokens)}


def submit_batch(cfg, requests, *, client=None):
    """일괄 처리 제출 → 배치 ID. 기록은 결과를 거둘 때(batch_results) 한다."""
    client = client or make_client(cfg)
    return client.messages.batches.create(requests=list(requests)).id


def batch_results(conn, cfg, batch_id, *, stage, items=None, run_id=None, client=None):
    """끝난 배치의 결과 → {custom_id: LLMResult}. 아직 끝나지 않았으면 None.
    결과 순서를 믿지 않고 custom_id로 맞춘다. 비용은 50%. items: {custom_id: 공고 수}(기록용)."""
    client = client or make_client(cfg)
    if _get(client.messages.batches.retrieve(batch_id), "processing_status") != "ended":
        return None
    model, out, now = cfg["CLAUDE_MODEL"], {}, datetime.now().isoformat(timespec="seconds")
    for r in client.messages.batches.results(batch_id):
        cid, result = _get(r, "custom_id"), _get(r, "result")
        if _get(result, "type") == "succeeded":
            res = read_message(_get(result, "message"), model, batch=True)
        else:
            err = _get(result, "error")
            res = LLMResult(data=None, outcome="error", model=model, served_model=None,
                            error=f"{_get(result, 'type')}: {_get(_get(err, 'error'), 'message') or err or ''}"[:500])
        res.request_id = f"batch:{batch_id}"
        record(conn, res, stage=stage, mode="batch", items=(items or {}).get(cid), started_at=now, ms=None, run_id=run_id)
        out[cid] = res
    return out

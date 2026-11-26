"""공고 유형 분류(ADR-045·048·049, 00 5.4·부록 B.1) — classify_v2 프롬프트로 50건 묶음을 분류해 announcement_labels 에 둔다.

- 입력 항목은 검증 스크립트(plan/validation/make_input.py)와 같다: 제목·말머리·상태·기간·본문 앞 300자(연락처 가림)·첨부 이름.
- 검사: 빠진 ann_id·class에 맞지 않는 sub는 그 공고만 한 번 다시 보낸다. 그래도 안 되면 '수동 확인'.
  거절(대체 모델까지)은 '분류 보류', 잘림(max_tokens)은 묶음을 반으로 나눠 다시, API 오류는 기록하고 다음 묶음.
- 저장은 labels.save_api 로 한다(source='manual' 행은 덮어쓰지 않는다).
- 같은 input_hash로 이미 라벨이 있으면 다시 보내지 않는다(redo 제외).
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

from . import labels, llm
from .mask import mask_contacts

PROMPT_VERSION = "classify_v2"
PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
CHUNK = 50
MAX_TOKENS = 8000            # 50건 묶음
BATCH_KEY = "llm_batches"    # app_kv: 제출한 일괄 처리 목록(거둘 때 지운다)


def prompt():
    """→ (시스템 프롬프트, JSON 스키마)"""
    return ((PROMPT_DIR / f"{PROMPT_VERSION}.system.md").read_text(encoding="utf-8"),
            json.loads((PROMPT_DIR / f"{PROMPT_VERSION}.schema.json").read_text(encoding="utf-8")))


def build_items(conn, ann_ids):
    """공고 번호 → 분류 입력 항목 목록(주어진 순서, 없는 번호는 뺀다)."""
    out = []
    for ann_id in ann_ids:
        r = conn.execute(
            "SELECT a.ann_id, b.code AS board, a.post_no, a.title, a.biz, a.site_status, a.period_raw, a.posted_at, a.list_date, a.body "
            "FROM announcements a JOIN boards b ON b.board_id = a.board_id WHERE a.ann_id = ?", (ann_id,)).fetchone()
        if r is None:
            continue
        files = [x[0] for x in conn.execute("SELECT name FROM attachments WHERE ann_id = ? ORDER BY seq", (ann_id,))]
        out.append({"ann_id": r["ann_id"], "board": r["board"], "post_no": r["post_no"], "title": r["title"], "biz": r["biz"] or "",
                    "site_status": r["site_status"] or "", "period": r["period_raw"] or "", "posted": r["posted_at"] or r["list_date"],
                    "body": mask_contacts(r["body"] or "")[:300], "files": [(n or "")[:60] for n in files[:6]]})
    return out


def input_hash(item):
    """입력 항목이 같으면 같은 값(sha256 앞 16자)."""
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def user_text(items):
    return "다음 items를 분류하세요.\n<items>\n" + json.dumps(items, ensure_ascii=False) + "\n</items>\n"


def targets(conn, *, board=None, limit=None, redo=False):
    """분류할 공고 번호(게시일 최신순). manual 라벨은 늘 빼고, redo가 아니면 같은 입력으로 이미 라벨이 있는 공고도 뺀다."""
    sql = ("SELECT a.ann_id, l.source, l.input_hash FROM announcements a JOIN boards b ON b.board_id = a.board_id "
           "LEFT JOIN announcement_labels l ON l.ann_id = a.ann_id")
    args = []
    if board:
        sql += " WHERE b.code = ?"
        args.append(board)
    sql += " ORDER BY a.posted_at DESC, a.ann_id DESC"
    out = []
    for r in conn.execute(sql, args).fetchall():
        if r["source"] == "manual":
            continue
        if not redo and r["input_hash"] and r["input_hash"] == input_hash(build_items(conn, [r["ann_id"]])[0]):
            continue
        out.append(r["ann_id"])
        if limit and len(out) >= limit:
            break
    return out


def _valid(r):
    return r.get("class") in labels.CLASSES and r.get("sub") in labels.SUBS[r["class"]]


def _parse(res, ids):
    """ok 응답 → ({ann_id: 결과}, 다시 보낼 ann_id 목록). 묶음에 없는 ann_id는 버린다."""
    got = {}
    for r in (res.data or {}).get("results") or []:
        if isinstance(r, dict) and r.get("ann_id") in ids and r["ann_id"] not in got:
            got[r["ann_id"]] = r
    return got, [i for i in ids if i not in got or not _valid(got[i])]


class _Run:
    def __init__(self, conn, cfg, *, run_id=None, client=None, say=print):
        self.conn, self.cfg, self.run_id, self.client, self.say = conn, cfg, run_id, client, say
        self.system, self.schema = prompt()
        self.stat = {"items": 0, "calls": 0, "확정": 0, "수동 확인": 0, "분류 보류": 0, "kept_manual": 0, "errors": 0,
                     "cost_usd": 0.0}

    def save(self, item, *, cls, sub, status, confidence=None, reason=None, model=None, request_id=None):
        ok = labels.save_api(self.conn, item["ann_id"], cls=cls, sub=sub, confidence=confidence, reason=reason, status=status,
                             prompt_version=PROMPT_VERSION, model=model, request_id=request_id, input_hash=input_hash(item))
        self.stat[status if ok else "kept_manual"] += 1

    def save_result(self, item, r, res):
        """검사를 통과한 결과는 확정, class에 맞지 않는 sub는 수동 확인(sub 비움), 결과가 없으면 수동 확인(class 비움)."""
        if r is not None and _valid(r):
            self.save(item, cls=r["class"], sub=r["sub"], status="확정", confidence=r.get("confidence"), reason=r.get("reason"),
                      model=res.served_model, request_id=res.request_id)
        elif r is not None and r.get("class") in labels.CLASSES:
            self.save(item, cls=r["class"], sub=None, status="수동 확인", confidence=r.get("confidence"),
                      reason=f"sub '{r.get('sub')}'가 class에 맞지 않음: {r.get('reason') or ''}"[:200], model=res.served_model,
                      request_id=res.request_id)
        else:
            self.save(item, cls=None, sub=None, status="수동 확인", reason="응답에 없음", model=res.served_model,
                      request_id=res.request_id)

    def hold(self, items, res):
        for x in items:
            self.save(x, cls=None, sub=None, status="분류 보류", reason=f"거절({res.outcome})", model=res.served_model,
                      request_id=res.request_id)

    def call(self, items):
        self.stat["calls"] += 1
        res = llm.call_json(self.conn, self.cfg, stage="classify", system=self.system, user_text=user_text(items), schema=self.schema,
                            max_tokens=MAX_TOKENS, items=len(items), run_id=self.run_id, client=self.client)
        self.stat["cost_usd"] += res.cost_usd or 0
        return res

    def handle(self, items, res, *, retry=True):
        """한 묶음의 응답을 처리한다. 잘리면 반으로 나눠 다시 부른다(retry=False인 일괄 결과는 저장하지 않고 넘긴다)."""
        if res.outcome == "refusal":
            self.hold(items, res)
        elif res.outcome == "max_tokens" and retry and len(items) > 1:
            half = len(items) // 2
            for part in (items[:half], items[half:]):
                self.handle(part, self.call(part))
        elif res.outcome != "ok":
            self.stat["errors"] += 1
            self.say(f"분류 묶음 {len(items)}건 실패: {res.outcome} {res.error or ''}".rstrip())
        else:
            by = {x["ann_id"]: x for x in items}
            got, again = _parse(res, list(by))
            for i, r in got.items():
                if i not in again:
                    self.save_result(by[i], r, res)
            if again:
                self.again([by[i] for i in again], got, res)
        self.conn.commit()

    def again(self, items, first, first_res):
        """빠졌거나 sub가 맞지 않은 공고만 한 번 다시 보낸다. 그래도 안 되면 수동 확인."""
        res = self.call(items)
        if res.outcome == "refusal":
            self.hold(items, res)
            return
        got = _parse(res, [x["ann_id"] for x in items])[0] if res.outcome == "ok" else {}
        for x in items:
            r = got.get(x["ann_id"])
            if r is not None:
                self.save_result(x, r, res)
            else:
                self.save_result(x, first.get(x["ann_id"]), first_res)


def run(conn, cfg, ann_ids, *, run_id=None, client=None, say=print):
    """동기 호출로 분류한다(50건 묶음). 키가 없으면 llm.make_client 가 RuntimeError.
    → {"items", "calls", "확정", "수동 확인", "분류 보류", "kept_manual", "errors", "cost_usd"}"""
    client = client or llm.make_client(cfg)
    r = _Run(conn, cfg, run_id=run_id, client=client, say=say)
    items = build_items(conn, ann_ids)
    r.stat["items"] = len(items)
    for i in range(0, len(items), CHUNK):
        chunk = items[i:i + CHUNK]
        r.handle(chunk, r.call(chunk))
    r.stat["cost_usd"] = round(r.stat["cost_usd"], 6)
    return r.stat


def _batches(conn):
    row = conn.execute("SELECT value FROM app_kv WHERE key=?", (BATCH_KEY,)).fetchone()
    return json.loads(row[0]) if row and row[0] else []


def _set_batches(conn, data):
    conn.execute("INSERT INTO app_kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (BATCH_KEY, json.dumps(data, ensure_ascii=False)))
    conn.commit()


def submit_batch(conn, cfg, ann_ids, *, client=None, say=print):
    """일괄 처리로 제출하고 배치 ID를 app_kv['llm_batches']에 남긴다(묶음별 입력 항목 포함). → 배치 ID 또는 None(대상 없음)"""
    items = build_items(conn, ann_ids)
    if not items:
        return None
    system, schema = prompt()
    chunks = {f"classify-{i // CHUNK + 1:03d}": items[i:i + CHUNK] for i in range(0, len(items), CHUNK)}
    reqs = [llm.batch_request(cfg, cid, system=system, user_text=user_text(c), schema=schema, max_tokens=MAX_TOKENS)
            for cid, c in chunks.items()]
    batch_id = llm.submit_batch(cfg, reqs, client=client)
    _set_batches(conn, _batches(conn) + [{"id": batch_id, "stage": "classify", "submitted_at": datetime.now().isoformat(timespec="seconds"),
                                          "chunks": chunks}])
    say(f"분류 일괄 제출: {batch_id} ({len(items)}건, {len(chunks)}묶음)")
    return batch_id


def collect(conn, cfg, *, run_id=None, client=None, say=print):
    """끝난 분류 배치를 거둬 저장한다. 거절은 분류 보류(대체 없음), 빠진·sub 불일치는 동기로 한 번 다시, 잘림·오류는 저장하지 않는다
    (다음 실행에서 동기 대상이 된다). → 통계 + {"batches", "pending"}"""
    client = client or llm.make_client(cfg)
    r = _Run(conn, cfg, run_id=run_id, client=client, say=say)
    left, done = [], 0
    for b in _batches(conn):
        if b.get("stage") != "classify":
            left.append(b)
            continue
        got = llm.batch_results(conn, cfg, b["id"], stage="classify", items={k: len(v) for k, v in b["chunks"].items()}, run_id=run_id,
                                client=client)
        if got is None:
            left.append(b)
            continue
        done += 1
        for cid, items in b["chunks"].items():
            r.stat["items"] += len(items)
            res = got.get(cid)
            if res is None:
                r.stat["errors"] += 1
                say(f"배치 {b['id']}에 {cid} 결과 없음")
                continue
            r.stat["cost_usd"] += res.cost_usd or 0
            r.handle(items, res, retry=False)
    _set_batches(conn, left)
    r.stat["cost_usd"] = round(r.stat["cost_usd"], 6)
    return {**r.stat, "batches": done, "pending": sum(b.get("stage") == "classify" for b in left)}


def import_cli(conn, run_dir):
    """plan/validation/run_cli.sh 결과 폴더(in/<board>/chunk-NN.jsonl, out/<board>/chunk-NN.json)를 라벨로 넣는다(API 비용 없음).
    request_id='cli:<실행 이름>', model은 meta.txt의 model.
    → {"items", "확정", "수동 확인", "missing", "failed_chunks", "kept_manual", "unknown"}"""
    run_dir = Path(run_dir)
    meta = {}
    if (run_dir / "meta.txt").exists():
        for line in (run_dir / "meta.txt").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            meta[k.strip()] = v.strip()
    stat = {"items": 0, "확정": 0, "수동 확인": 0, "missing": 0, "failed_chunks": 0, "kept_manual": 0, "unknown": 0}
    req = f"cli:{run_dir.name}"
    for inp in sorted((run_dir / "in").glob("*/chunk-*.jsonl")):
        items = [json.loads(line) for line in inp.read_text(encoding="utf-8").splitlines() if line.strip()]
        stat["items"] += len(items)
        try:
            j = json.loads((run_dir / "out" / inp.parent.name / f"{inp.stem}.json").read_text(encoding="utf-8"))
            results = None if j.get("is_error") else j["structured_output"]["results"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            results = None
        if not isinstance(results, list):
            stat["failed_chunks"] += 1
            stat["missing"] += len(items)
            continue
        got = {}
        for r in results:
            if isinstance(r, dict) and r.get("ann_id") not in got:
                got[r.get("ann_id")] = r
        model = meta.get("model") or next(iter(j.get("modelUsage") or {}), None)
        for x in items:
            r = got.get(x["ann_id"])
            if r is None:
                stat["missing"] += 1
                continue
            if not conn.execute("SELECT 1 FROM announcements WHERE ann_id=?", (x["ann_id"],)).fetchone():
                stat["unknown"] += 1
                continue
            if _valid(r):
                kw = dict(cls=r["class"], sub=r["sub"], status="확정", reason=r.get("reason"))
            else:
                kw = dict(cls=r.get("class") if r.get("class") in labels.CLASSES else None, sub=None, status="수동 확인",
                          reason=f"sub '{r.get('sub')}'가 class에 맞지 않음: {r.get('reason') or ''}"[:200])
            ok = labels.save_api(conn, x["ann_id"], confidence=r.get("confidence"), prompt_version=meta.get("prompt") or PROMPT_VERSION,
                                 model=model, request_id=req, input_hash=input_hash(x), **kw)
            stat[kw["status"] if ok else "kept_manual"] += 1
    conn.commit()
    return stat

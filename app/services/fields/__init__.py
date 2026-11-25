"""상세화면 표준 필드(ADR-045·051) — 공고 × 다섯 칸을 announcement_fields 에 둔다.

- load·context·input_hash: 2단계(코디네이터). targets·run: 4단계(부록 C.1·C.8).
- 원래 칸(announcements.period_raw·start_at·end_at·body)은 덮어쓰지 않는다(원칙 P4).
"""
import hashlib
import json
from collections import Counter
from datetime import datetime

from .. import labels
from .model import FIELDS, Att, Doc, FieldValue

VALUE_MAX, EVIDENCE_MAX = 1500, 200

COLS = ("field", "value", "start_at", "end_at", "source", "source_ref", "evidence", "status", "note", "method", "prompt_version",
        "input_hash", "extracted_at")


def load(conn, ann_id):
    """저장된 칸을 FIELDS 순서로 돌려준다(화면용). 아직 정리하지 않은 공고면 []."""
    rows = {r["field"]: {k: r[k] for k in COLS} for r in
            conn.execute(f"SELECT {', '.join(COLS)} FROM announcement_fields WHERE ann_id=?", (ann_id,))}
    return [rows[f] for f in FIELDS if f in rows]


def context(conn, ann_id):
    """공고 하나의 추출 입력. 첨부는 글자를 읽은(text_status='ok') 것만 담는다. 공고가 없으면 None."""
    r = conn.execute("SELECT a.*, b.code AS board FROM announcements a JOIN boards b ON b.board_id = a.board_id WHERE a.ann_id=?",
                     (ann_id,)).fetchone()
    if r is None:
        return None
    lab = labels.get(conn, ann_id) or {}
    atts = [Att(seq=x["seq"], name=x["name"] or "", ext=(x["ext"] or "").lower(), text=x["text_body"] or "", engine=x["text_engine"])
            for x in conn.execute("SELECT seq, name, ext, text_body, text_engine FROM attachments "
                                  "WHERE ann_id=? AND text_status='ok' ORDER BY seq", (ann_id,))]
    return Doc(ann_id=ann_id, board=r["board"], cls=lab.get("class"), sub=lab.get("sub"), title=r["title"] or "", biz=r["biz"] or "",
               period_raw=r["period_raw"] or "", start_at=r["start_at"], end_at=r["end_at"], body=r["body"] or "", attachments=atts)


def input_hash(doc):
    """제목·말머리·기간·본문·첨부 글자·유형이 같으면 같은 값(sha256 앞 16자). 바뀌면 다시 추출한다."""
    data = [doc.title, doc.biz, doc.period_raw, doc.start_at, doc.end_at, doc.body, [(a.name, a.text) for a in doc.attachments], doc.cls]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _stored(conn, ann_id):
    return {r["field"]: dict(r) for r in conn.execute("SELECT field, status, method, input_hash FROM announcement_fields WHERE ann_id=?", (ann_id,))}


def targets(conn, *, board=None, limit=None, redo=False):
    """정리할 공고 번호(게시일 최신순). redo가 아니면 다섯 칸이 모두 같은 입력(input_hash)으로 저장된 공고는 뺀다."""
    sql = "SELECT a.ann_id FROM announcements a JOIN boards b ON b.board_id = a.board_id"
    args = []
    if board:
        sql += " WHERE b.code = ?"
        args.append(board)
    sql += " ORDER BY a.posted_at DESC, a.ann_id DESC"
    out = []
    for (ann_id,) in conn.execute(sql, args).fetchall():
        if not redo:
            have = _stored(conn, ann_id)
            if len(have) == len(FIELDS) and {r["input_hash"] for r in have.values()} == {input_hash(context(conn, ann_id))}:
                continue
        out.append(ann_id)
        if limit and len(out) >= limit:
            break
    return out


def save(conn, ann_id, fv, h):
    """칸 하나를 저장한다(덮어씀). 커밋은 부르는 쪽이 한다."""
    conn.execute(
        "INSERT INTO announcement_fields (ann_id, field, value, start_at, end_at, source, source_ref, evidence, status, note, method, "
        "prompt_version, input_hash, extracted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(ann_id, field) DO UPDATE SET value=excluded.value, start_at=excluded.start_at, end_at=excluded.end_at, "
        "source=excluded.source, source_ref=excluded.source_ref, evidence=excluded.evidence, status=excluded.status, note=excluded.note, "
        "method=excluded.method, prompt_version=excluded.prompt_version, input_hash=excluded.input_hash, extracted_at=excluded.extracted_at",
        (ann_id, fv.field, (fv.value or None) and fv.value[:VALUE_MAX], fv.start_at, fv.end_at, fv.source, fv.source_ref,
         (fv.evidence or None) and fv.evidence[:EVIDENCE_MAX], fv.status, fv.note, fv.method, fv.prompt_version, h,
         datetime.now().isoformat(timespec="seconds")))


def run(conn, cfg, ann_ids, *, api=False, api_max=50, run_id=None, client=None, say=print, redo=False):
    """공고마다 규칙으로 다섯 칸을 정리하고(부록 C.1·C.8), api=True면 공모지원사업의 '미확인' 칸을 API로 보완한다(실행당 api_max건).
    → {"done", "skipped", "status": {상태: 칸 수}, "api_items", "api_found", "errors"}"""
    from . import rules
    res = {"done": 0, "skipped": 0, "status": Counter(), "api_items": 0, "api_found": 0, "errors": 0}
    for ann_id in ann_ids:
        try:
            doc = context(conn, ann_id)
            if doc is None:
                continue
            h = input_hash(doc)
            have = _stored(conn, ann_id)
            if not redo and len(have) == len(FIELDS) and all(r["input_hash"] == h for r in have.values()):
                res["skipped"] += 1
                continue
            got = rules.extract(doc)
            missing = []
            for f in FIELDS:
                fv = got.get(f) or FieldValue(field=f, status="미확인")
                prev = have.get(f)
                if fv.status == "미확인":
                    if prev and prev["method"] == "api" and prev["input_hash"] == h:
                        continue                           # 같은 입력으로 이미 API를 시도한 칸은 그대로 둔다
                    missing.append(f)
                save(conn, ann_id, fv, h)
            if api and doc.cls == "공모지원사업" and missing and res["api_items"] < api_max:
                from . import api as fields_api
                res["api_items"] += 1
                for f, fv in fields_api.supplement(conn, cfg, doc, missing, run_id=run_id, client=client).items():
                    save(conn, ann_id, fv, h)
                    res["api_found"] += fv.status == "확인"
            conn.commit()
            for r in conn.execute("SELECT status FROM announcement_fields WHERE ann_id=?", (ann_id,)):
                res["status"][r["status"]] += 1
            res["done"] += 1
        except Exception as e:  # noqa: BLE001 — 한 공고 실패로 전체를 멈추지 않는다
            conn.rollback()
            res["errors"] += 1
            say(f"표준 필드 {ann_id} 실패: {type(e).__name__}: {e}")
    res["status"] = dict(res["status"])
    return res


# ── API 보완을 run() 밖에서 돌리는 길(5.5: --dump-input·--import-cli·--batch·--collect) ──
def api_pending(conn, ann_ids):
    """공모지원사업 중 규칙으로 못 찾은 칸이 남은 공고 → [(doc, 보낼 칸, input_hash)]. 같은 입력으로 API를 이미 시도한 칸은 뺀다."""
    from .api import API_FIELDS
    out = []
    for ann_id in ann_ids:
        doc = context(conn, ann_id)
        if doc is None or doc.cls != "공모지원사업":
            continue
        h = input_hash(doc)
        rows = conn.execute("SELECT field, method, input_hash FROM announcement_fields WHERE ann_id=? AND status='미확인'", (ann_id,)).fetchall()
        want = [r["field"] for r in rows if r["field"] in API_FIELDS and r["input_hash"] == h and r["method"] == "rule"]
        if want:
            out.append((doc, want, h))
    return out


def dump_input(conn, ann_ids, out_dir):
    """API에 보낼 입력을 파일로만 쓴다(CLI 검증용): <out>/in/<ann_id>.txt(사용자 글)·<ann_id>.json(칸·입력 해시). → 건수"""
    from pathlib import Path

    from . import api
    d = Path(out_dir) / "in"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for doc, want, h in api_pending(conn, ann_ids):
        (d / f"{doc.ann_id}.txt").write_text(api.build_input(doc, want), encoding="utf-8")
        (d / f"{doc.ann_id}.json").write_text(json.dumps({"ann_id": doc.ann_id, "fields": want, "input_hash": h}, ensure_ascii=False),
                                              encoding="utf-8")
        n += 1
    return n


def _apply(conn, doc, want, h, data):
    from . import api
    got = api.interpret(doc, want, data)
    for fv in got.values():
        save(conn, doc.ann_id, fv, h)
    return sum(fv.status == "확인" for fv in got.values())


def import_cli(conn, run_dir):
    """dump_input 폴더를 claude -p로 돌린 결과(<run>/out/<ann_id>.json의 structured_output)를 넣는다.
    입력 뒤 공고가 바뀌었으면(input_hash 다름) 넣지 않는다. → {"items", "found", "stale", "failed"}"""
    from pathlib import Path
    run = Path(run_dir)
    res = {"items": 0, "found": 0, "stale": 0, "failed": 0}
    for meta_p in sorted((run / "in").glob("*.json")):
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        doc = context(conn, meta["ann_id"])
        if doc is None or input_hash(doc) != meta["input_hash"]:
            res["stale"] += 1
            continue
        try:
            out = json.loads((run / "out" / f"{meta['ann_id']}.json").read_text(encoding="utf-8"))
            data = out.get("structured_output")
        except (OSError, ValueError):
            data = None
        if not data:
            res["failed"] += 1
            continue
        res["found"] += _apply(conn, doc, meta["fields"], meta["input_hash"], data)
        res["items"] += 1
        conn.commit()
    return res


BATCH_KEY = "llm_batches"


def _batches(conn):
    row = conn.execute("SELECT value FROM app_kv WHERE key=?", (BATCH_KEY,)).fetchone()
    return json.loads(row[0]) if row and row[0] else []


def _set_batches(conn, data):
    conn.execute("INSERT INTO app_kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (BATCH_KEY, json.dumps(data, ensure_ascii=False)))
    conn.commit()


def submit_batch(conn, cfg, ann_ids, *, client=None):
    """API 보완을 일괄 처리로 제출(공고 하나 = 요청 하나)하고 app_kv['llm_batches']에 남긴다. → 배치 ID 또는 None"""
    from .. import llm
    from . import api
    todo = api_pending(conn, ann_ids)
    if not todo:
        return None
    system, schema = api.prompt()
    reqs = [llm.batch_request(cfg, f"extract-{doc.ann_id}", system=system, user_text=api.build_input(doc, want), schema=schema,
                              max_tokens=api.MAX_TOKENS) for doc, want, h in todo]
    bid = llm.submit_batch(cfg, reqs, client=client)
    _set_batches(conn, _batches(conn) + [{"id": bid, "stage": "extract", "submitted_at": datetime.now().isoformat(timespec="seconds"),
                                          "chunks": {f"extract-{doc.ann_id}": {"ann_id": doc.ann_id, "fields": want, "input_hash": h}
                                                     for doc, want, h in todo}}])
    return bid


def collect(conn, cfg, *, run_id=None, client=None):
    """끝난 추출 배치를 거둬 저장한다. → {"batches", "pending", "items", "found", "stale", "failed"}"""
    from .. import llm
    res = {"batches": 0, "pending": 0, "items": 0, "found": 0, "stale": 0, "failed": 0}
    keep = []
    for b in _batches(conn):
        if b.get("stage") != "extract":
            keep.append(b)
            continue
        got = llm.batch_results(conn, cfg, b["id"], stage="extract", items={cid: 1 for cid in b["chunks"]}, run_id=run_id, client=client)
        if got is None:
            res["pending"] += 1
            keep.append(b)
            continue
        res["batches"] += 1
        for cid, meta in b["chunks"].items():
            doc = context(conn, meta["ann_id"])
            r = got.get(cid)
            if doc is None or input_hash(doc) != meta["input_hash"]:
                res["stale"] += 1
            elif r is None or r.outcome != "ok":
                from .api import _unknown
                for f in meta["fields"]:
                    save(conn, doc.ann_id, _unknown(f, f"API {r.outcome if r else 'missing'}"), meta["input_hash"])
                res["failed"] += 1
            else:
                res["found"] += _apply(conn, doc, meta["fields"], meta["input_hash"], r.data)
                res["items"] += 1
        conn.commit()
    _set_batches(conn, keep)
    return res

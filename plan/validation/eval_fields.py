"""표준 필드 지표(00 부록 E.3) — 정답표와 예측을 비교해 칸·기관별 채움률·정답률·상태 일치율·인용 불일치 수를 낸다.

사용: python plan/validation/eval_fields.py [--pred rules|db] [--name 이름] [--gold plan/validation/gold/fields_gold.jsonl]
                                          [--src data/validation/gold-src] [--db data/gongmo.db] [--cost-dir 폴더] [--dump 파일]
- rules(규칙만): gold-src 원문(meta.json·body.txt·att-*.md)으로 Doc을 만들어 rules.extract를 돌린다.
  첨부는 파이프라인처럼 attach_text.pick_files로 3개(zip 안은 2개)까지 고른다. 유형은 정답표 class(없으면 meta의 기준 분류).
- db(규칙 + API): DB의 announcement_fields를 읽는다(읽기 전용). 공고는 게시판·게시물 번호로 찾는다.
결과: plan/validation/gold/report-<이름>.md. 정답표가 없으면 채움률만 적는다. 검수 전(reviewed=false) 정답표면 '잠정'을 붙인다.

판정(E.3): 확인 칸은 정답 key가 예측 value에 들어 있으면(공백·기호 무시) 정답. period는 시작·마감 날짜가 같으면 정답(시각 무시).
미확인·해당 없음은 상태가 같으면 정답. 채움 = 값을 보여 주는 칸(확인 + 충돌).
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.services.attach_text import pick_files  # noqa: E402
from app.services.fields import rules  # noqa: E402
from app.services.fields.model import FIELDS, Att, Doc  # noqa: E402

ORG = {"nipa_business": "NIPA", "nia_bid": "NIA", "kca_bidding": "KCA", "rapa_notice": "RAPA"}
SHOWN = ("확인", "충돌")
MONTHLY = 18          # 월 신규 공모지원사업 추정 건수(E.3)
DOC_EXT = ("hwp", "hwpx", "pdf", "docx", "xlsx")


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def load_doc(d, cls):
    """gold-src/<ann_id>/ → (meta, Doc). 첨부 글자는 kordoc 결과(att-*.md), zip은 '### 안의 이름' 머리로 잇는다(부록 C.7)."""
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    files = json.loads((d / "attachments.json").read_text(encoding="utf-8"))
    tops = {}
    for x in files:
        m = re.match(r"att-(\d+)(?:-(\d+))?\.md$", x.get("md") or "")
        if not m or not x["status"].startswith("ok"):
            continue
        seq = int(m.group(1))
        t = tops.setdefault(seq, {"seq": seq, "name": x["name"], "ext": _ext(x["name"]), "inner": []})
        text = (d / x["md"]).read_text(encoding="utf-8", errors="replace")
        if m.group(2):
            t["inner"].append({"seq": int(m.group(2)), "name": x["inner"], "ext": _ext(x["inner"]), "text": text})
        else:
            t["text"] = text
    atts = []
    for r in pick_files(list(tops.values()), 3):
        if r["inner"]:
            text = "\n\n".join(f"### {p['name']}\n{p['text']}" for p in pick_files(r["inner"], 2, readable=DOC_EXT))
        else:
            text = r.get("text") or ""
        if text.strip():
            atts.append(Att(seq=r["seq"], name=r["name"], ext=r["ext"], text=text, engine="kordoc"))
    body = (d / "body.txt").read_text(encoding="utf-8")
    return meta, Doc(ann_id=meta["ann_id"], board=meta["board"], cls=cls, sub=None, title=meta["title"] or "", biz=meta["biz"] or "",
                     period_raw=meta["period_raw"] or "", start_at=meta["start_at"], end_at=meta["end_at"], body=body, attachments=atts)


def _samples(src):
    for d in sorted(p for p in Path(src).iterdir() if (p / "meta.json").exists()):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        yield d, meta, (meta["board"], str(meta["post_no"]))


def predict_rules(src, gold_class):
    out = {}
    for d, meta, key in _samples(src):
        cls = gold_class.get(key, meta.get("ref_class"))
        _, doc = load_doc(d, cls)
        out[key] = {"ann_id": meta["ann_id"], "class": cls, "fields": {f: asdict(v) for f, v in rules.extract(doc).items()}}
    return out


def predict_db(db, src, gold_class):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out = {}
    for _, meta, key in _samples(src):
        r = conn.execute("SELECT a.ann_id FROM announcements a JOIN boards b ON b.board_id = a.board_id WHERE b.code=? AND a.post_no=?",
                         key).fetchone()
        if not r:
            continue
        rows = {x["field"]: dict(x) for x in conn.execute("SELECT * FROM announcement_fields WHERE ann_id=?", (r["ann_id"],))}
        fields = {f: rows.get(f) or {"field": f, "status": "미확인", "value": None, "method": "none"} for f in FIELDS}
        out[key] = {"ann_id": r["ann_id"], "class": gold_class.get(key, meta.get("ref_class")), "fields": fields}
    conn.close()
    return out


def _norm(s):
    return re.sub(r"[\W_]+", "", s or "")


def judge(p, g):
    """예측 칸 p가 정답 g와 맞는지."""
    if p["status"] not in SHOWN:
        return p["status"] == g["status"]
    if g["status"] != "확인":
        return False
    if g["field"] == "period":
        pairs = [((p.get("start_at") or "")[:10], (g.get("start_at") or "")[:10]),
                 ((p.get("end_at") or "")[:10], (g.get("end_at") or "")[:10])]
        return any(b for _, b in pairs) and all(a == b for a, b in pairs if b)
    key = _norm(g.get("key"))
    return bool(key) and key in _norm(p.get("value"))


def pct(n, d):
    return f"{n}/{d} ({n / d * 100:.1f}%)" if d else "-"


def table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def tally(pairs):
    """[(예측, 정답 또는 None)] → 지표 Counter. '해당 없음' 칸(정답표가 있으면 정답 기준)은 대상에서 뺀다."""
    c = Counter()
    for p, g in pairs:
        if (g or p)["status"] == "해당 없음":
            continue
        shown = p["status"] in SHOWN
        c["n"] += 1
        c["shown"] += shown
        c["conflict"] += p["status"] == "충돌"
        c["cite"] += p.get("method") == "api" and "인용" in (p.get("note") or "")
        if g:
            c["g"] += 1
            c["g_shown"] += shown
            c["g_ok"] += shown and judge(p, g)
            c["state"] += ("확인" if shown else p["status"]) == g["status"]
    return c


def costs(folder):
    vals = []
    for f in Path(folder).rglob("*.json"):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(j, dict) and "total_cost_usd" in j:
            vals.append(j["total_cost_usd"] or 0)
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", choices=("rules", "db"), default="rules")
    ap.add_argument("--name")
    ap.add_argument("--gold", default=str(ROOT / "plan" / "validation" / "gold" / "fields_gold.jsonl"))
    ap.add_argument("--src", default=str(ROOT / "data" / "validation" / "gold-src"))
    ap.add_argument("--db", default=str(ROOT / "data" / "gongmo.db"))
    ap.add_argument("--cost-dir", help="CLI 추출 실행 폴더(*.json의 total_cost_usd를 합친다)")
    ap.add_argument("--dump", help="예측을 JSONL로 쓸 파일")
    a = ap.parse_args()
    name = a.name or a.pred
    gold, gold_class = {}, {}
    if Path(a.gold).exists():
        for ln in Path(a.gold).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                g = json.loads(ln)
                key = (g["board"], str(g["post_no"]))
                gold[(key, g["field"])] = g
                gold_class[key] = g.get("class")
    pred = predict_rules(a.src, gold_class) if a.pred == "rules" else predict_db(a.db, a.src, gold_class)
    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as f:
            for (board, post_no), x in sorted(pred.items()):
                f.write(json.dumps({"board": board, "post_no": post_no, **x}, ensure_ascii=False) + "\n")

    items = [(key, x["class"], f, x["fields"][f], gold.get((key, f))) for key, x in pred.items() for f in FIELDS]
    has_gold = bool(gold)
    provisional = has_gold and not all(g.get("reviewed") for g in gold.values())
    tag = " (잠정)" if provisional else ""

    def pick(**w):
        return [(p, g) for k, c, f, p, g in items
                if all({"board": k[0], "field": f, "cls": c}[n] == v for n, v in w.items())]

    def row(label, pairs):
        c = tally(pairs)
        r = [label, c["n"], pct(c["shown"], c["n"]), c["conflict"]]
        if has_gold:
            r += [pct(c["g_ok"], c["g_shown"]), pct(c["state"], c["g"])]
        return r + [c["cite"]]

    head = ["칸", "대상", "채움(확인+충돌)", "충돌"] + (["'확인' 정답률", "상태 일치율"] if has_gold else []) + ["인용 불일치"]
    t_field = table(head, [row(f, pick(field=f)) for f in FIELDS] + [row("**전체**", [(p, g) for *_, p, g in items])])
    boards = [b for b in ORG if any(i[0][0] == b for i in items)]

    def grid(num, den):
        return table(["기관 \\ 칸"] + list(FIELDS),
                     [[ORG[b]] + [pct((c := tally(pick(board=b, field=f)))[num], c[den]) for f in FIELDS] for b in boards])

    t_board = grid("shown", "n")
    t_board_ok = f"\n\n기관 × 칸 '확인' 정답률{tag}\n\n" + grid("g_ok", "g_shown") if has_gold else ""
    n_sup = len({k for k, c, *_ in items if c == "공모지원사업"})
    t_sup = table(head, [row(f, pick(cls="공모지원사업", field=f)) for f in FIELDS])
    kca = pick(board="kca_bidding", field="period")
    kca_fill = sum(p["status"] in SHOWN for p, _ in kca)

    wrong = []
    if has_gold:
        for key, cls, f, p, g in items:
            if not g or g["status"] == "해당 없음" and p["status"] == "해당 없음" or judge(p, g):
                continue
            if f == "period":
                pv, gv = f"{p.get('start_at')} ~ {p.get('end_at')}", f"{g.get('start_at')} ~ {g.get('end_at')}"
            else:
                pv, gv = (p.get("value") or "").replace("\n", " ")[:60], (g.get("key") or "")[:60]
            wrong.append([ORG.get(key[0], key[0]), key[1], f, p["status"], g["status"], pv.replace("|", "/"), gv.replace("|", "/")])
    short = {"확인": "O", "충돌": "C", "미확인": "-", "해당 없음": "·"}
    order = {b: i for i, b in enumerate(ORG)}
    t_ann = table(["기관", "게시물", "유형"] + list(FIELDS),
                  [[ORG.get(k[0], k[0]), k[1], x["class"] or "미분류"] + [short.get(x["fields"][f]["status"], "?") for f in FIELDS]
                   for k, x in sorted(pred.items(), key=lambda kv: (order.get(kv[0][0], 9), kv[0][1]))])

    cost = ""
    if a.cost_dir:
        v = costs(a.cost_dir)
        if v:
            avg = sum(v) / len(v)
            cost = (f"\n## 비용 (CLI 실행 폴더 `{a.cost_dir}`)\n\n"
                    f"- 건수 {len(v)} · 합계 ${sum(v):.4f} · 건당 평균 ${avg:.4f} · 최대 ${max(v):.4f}\n"
                    f"- 월 추정: 건당 평균 × {MONTHLY}건 = ${avg * MONTHLY:.3f}\n")
    mode = "규칙만(gold-src 원문 → rules.extract)" if a.pred == "rules" else "규칙 + API(DB announcement_fields)"
    gold_note = (f"정답표 `{Path(a.gold).name}` {len(gold)}줄" + (" — 검수 전이라 정답률은 잠정" if provisional else "")) if has_gold \
        else "정답표가 아직 없어 채움률만 적는다"
    report = f"""# 표준 필드 지표 — {name}{tag}

- 예측: {mode}
- 표본: {len(pred)}건(공모지원사업 {n_sup}건) · {gold_note}
- 채움 = 값을 보여 주는 칸(확인 + 충돌). 대상은 '해당 없음'을 뺀 칸{"(정답표 기준)" if has_gold else ""}
- 만든 명령: `python plan/validation/eval_fields.py --pred {a.pred} --name {name}`

## 칸별

{t_field}

## 기관 × 칸 채움률

{t_board}{t_board_ok}

## 공모지원사업 {n_sup}건 (관문 2 채움률: period ≥ 90%, content ≥ 80%, qualify ≥ 80%)

{t_sup}

## KCA period 채움 (관문 2: 10건 중 ≥ 8건)

- {kca_fill}/{len(kca)}건
{cost}
## 틀린 칸{tag}

{table(["기관", "게시물", "칸", "예측 상태", "정답 상태", "예측 값", "정답 key"], wrong) if wrong else ("없음" if has_gold else "정답표가 없어 판정하지 않았다")}

## 부록: 공고별 상태 (O 확인 · C 충돌 · - 미확인 · · 해당 없음)

{t_ann}
"""
    out = ROOT / "plan" / "validation" / "gold" / f"report-{name}.md"
    out.write_text(report, encoding="utf-8")
    print(f"{len(pred)}건 → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

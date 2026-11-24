"""검증 결과 평가 — 형식·누락 검사, 비용·시간 집계, 기준 분류(.team/out/classification.jsonl)와 일치율.

사용: python plan/validation/evaluate.py data/validation/<실행> [--ref .team/out/classification.jsonl]
결과: <실행>/results.jsonl, <실행>/report.md
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORG = {"nipa_business": "NIPA", "nia_bid": "NIA", "kca_bidding": "KCA", "rapa_notice": "RAPA"}
CL = ["공모지원사업", "입찰공고", "기타"]
SUB = {"입찰공고": {"입찰", "사전규격", "협상공모", "변경·취소"}, "공모지원사업": {"지원사업", "수행기관", "참가·교육", "변경·취소"},
       "기타": {"결과", "행사·설명회", "안내", "채용", "기타"}}


def table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--ref", default=str(ROOT / ".team" / "out" / "classification.jsonl"))
    a = ap.parse_args()
    run = Path(a.run)
    ref = {}
    if Path(a.ref).exists():
        ref = {r["ann_id"]: r for r in map(json.loads, Path(a.ref).read_text(encoding="utf-8").splitlines()) if r}
    res, stats, problems = {}, defaultdict(lambda: Counter()), []
    for inp in sorted((run / "in").glob("*/chunk-*.jsonl")):
        org = inp.parent.name
        want = [json.loads(l) for l in inp.read_text(encoding="utf-8").splitlines() if l.strip()]
        outp = run / "out" / org / (inp.stem + ".json")
        st = stats[org]
        st["calls"] += 1
        st["items"] += len(want)
        try:
            j = json.loads(outp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            problems.append(f"{org}/{inp.stem}: 출력 없음 또는 JSON 아님")
            st["failed_calls"] += 1
            continue
        if j.get("is_error") or not j.get("structured_output"):
            problems.append(f"{org}/{inp.stem}: 오류 응답 ({j.get('subtype')}, {j.get('stop_reason')})")
            st["failed_calls"] += 1
            continue
        st["cost_micro"] += round((j.get("total_cost_usd") or 0) * 1_000_000)
        st["ms"] += j.get("duration_ms") or 0
        u = j.get("usage") or {}
        st["in_tok"] += (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
        st["out_tok"] += u.get("output_tokens") or 0
        got = {r["ann_id"]: r for r in j["structured_output"]["results"]}
        for x in want:
            r = got.get(x["ann_id"])
            if r is None:
                st["missing"] += 1
                problems.append(f"{org}/{inp.stem}: ann_id {x['ann_id']} 빠짐")
                continue
            if r["sub"] not in SUB[r["class"]]:
                st["bad_sub"] += 1
                problems.append(f"{org}: ann_id {x['ann_id']} sub '{r['sub']}'가 class '{r['class']}'에 속하지 않음")
            res[x["ann_id"]] = {**r, "board": org, "title": x["title"]}
        st["extra"] += len(set(got) - {x["ann_id"] for x in want})
    with open(run / "results.jsonl", "w", encoding="utf-8") as f:
        for k in sorted(res):
            f.write(json.dumps(res[k], ensure_ascii=False) + "\n")

    orgs = [o for o in ORG if o in stats]
    t1 = table(["기관", "호출", "공고", "빠짐", "남는 id", "sub 불일치", "실패 호출", "입력 토큰", "출력 토큰", "비용(USD)", "호출당 평균(초)"],
               [[ORG[o], s["calls"], s["items"], s["missing"], s["extra"], s["bad_sub"], s["failed_calls"], f"{s['in_tok']:,}", f"{s['out_tok']:,}",
                 f"{s['cost_micro'] / 1e6:.3f}", f"{s['ms'] / max(1, s['calls'] - s['failed_calls']) / 1000:.1f}"] for o, s in ((o, stats[o]) for o in orgs)])
    tot = Counter()
    for o in orgs:
        tot.update(stats[o])
    by = defaultdict(Counter)
    for r in res.values():
        by[r["board"]][r["class"]] += 1
    t2 = table(["기관"] + CL + ["합계"], [[ORG[o]] + [by[o][c] for c in CL] + [sum(by[o].values())] for o in orgs])
    agree = defaultdict(lambda: [0, 0, 0])      # 비교 건수, class 일치, class+sub 일치
    conf = Counter()
    diffs = []
    for k, r in res.items():
        b = ref.get(k)
        if not b:
            continue
        g = agree[r["board"]]
        g[0] += 1
        g[1] += r["class"] == b["class"]
        g[2] += r["class"] == b["class"] and r["sub"] == b["sub"]
        conf[(b["class"], r["class"])] += 1
        if r["class"] != b["class"]:
            diffs.append((r["board"], k, b, r))
    allg = [sum(agree[o][i] for o in orgs) for i in range(3)]
    t3 = table(["기관", "비교", "분류 일치", "분류+하위 유형 일치"],
               [[ORG[o], agree[o][0], f"{agree[o][1]} ({agree[o][1] / max(1, agree[o][0]) * 100:.1f}%)", f"{agree[o][2]} ({agree[o][2] / max(1, agree[o][0]) * 100:.1f}%)"] for o in orgs]
               + [["**합계**", allg[0], f"**{allg[1]} ({allg[1] / max(1, allg[0]) * 100:.1f}%)**", f"**{allg[2]} ({allg[2] / max(1, allg[0]) * 100:.1f}%)**"]])
    t4 = table(["기준 \\ 이번"] + CL, [[c] + [conf[(c, d)] for d in CL] for c in CL])
    cf = Counter(r["confidence"] for r in res.values())
    diff_rows = [[ORG[o], k, b["class"] + "/" + b["sub"], r["class"] + "/" + r["sub"] + "/" + r["confidence"], r["title"][:45], r["reason"][:60]] for o, k, b, r in sorted(diffs)]
    meta = (run / "meta.txt").read_text(encoding="utf-8") if (run / "meta.txt").exists() else ""
    md = f"""# 분류 프롬프트 검증 결과

- 실행: `{run.name}` · {meta.strip().replace(chr(10), ' · ')}
- 기준(비교 대상): `{Path(a.ref).relative_to(ROOT) if Path(a.ref).is_relative_to(ROOT) else a.ref}` (Orca 분할 워커 분류)

## 1. 형식·비용

{t1}

- 합계: 호출 {tot['calls']} · 공고 {tot['items']} · 빠짐 {tot['missing']} · sub 불일치 {tot['bad_sub']} · 실패 호출 {tot['failed_calls']} · 비용 ${tot['cost_micro'] / 1e6:.3f}
- 확신도: high {cf['high']} · mid {cf['mid']} · low {cf['low']}

## 2. 분류 결과

{t2}

## 3. 기준 분류와 일치율

{t3}

## 4. 혼동표 (행: 기준, 열: 이번)

{t4}

## 5. 분류가 달라진 공고 ({len(diffs)}건)

{table(["기관", "ann_id", "기준", "이번(분류/하위/확신)", "제목", "이번 근거"], diff_rows) if diff_rows else "없음"}

## 6. 문제

{chr(10).join("- " + p for p in problems) if problems else "없음"}
"""
    (run / "report.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()

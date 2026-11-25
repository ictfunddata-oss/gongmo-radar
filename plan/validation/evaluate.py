"""검증 결과 평가 — 형식·누락 검사, 비용·시간 집계, 기준 분류(.team/out/classification.jsonl)와 일치율,
경계 규칙(B1·B2·B3, 00 부록 E.1) 준수율, 다른 실행과의 일치율(--compare).

사용: python plan/validation/evaluate.py data/validation/<실행> [--ref .team/out/classification.jsonl] [--compare data/validation/<다른 실행>]
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


# 경계 규칙(00 부록 E.1). 제목·말머리 기준. 위에서부터 처음 걸린 패턴 하나만 적용한다
#   (사전공개된 위탁연구는 규칙 4가 우선이라 B2를 B1보다 먼저 본다)
CHANGE = ("정정", "연장", "취소")


def boundary(title, biz):
    """→ (패턴, 기대 class, 기대 sub) 또는 None"""
    t = f"{biz or ''} {title or ''}"
    if "합격자" in t:
        return "B3", "기타", "채용"
    if ("사전규격" in t or "사전공개" in t) and not any(w in t for w in ("결과", "검토")):
        return "B2", "입찰공고", "변경·취소" if any(w in t for w in ("정정", "취소")) else "사전규격"
    if "위탁연구" in t and not any(w in t for w in ("결과", "선정", "합격")):
        return "B1", "입찰공고", "변경·취소" if any(w in t for w in CHANGE) else "협상공모"
    return None


def pct(n, d):
    return f"{n}/{d} ({n / d * 100:.1f}%)" if d else "0/0 (-)"


def table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--ref", default=str(ROOT / ".team" / "out" / "classification.jsonl"))
    ap.add_argument("--compare", help="두 실행 비교: 다른 실행 폴더(그 폴더의 results.jsonl)")
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
            if r is not None:
                r = {**r, "biz": x.get("biz", "")}
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
    # 경계 규칙 준수(B1·B2·B3)와 패턴 밖 공고의 기준 대비 class 일치
    pat = defaultdict(lambda: [0, 0, 0])        # 건수, class 일치, class+sub 일치
    pat_bad, out_n, out_ok = [], 0, 0
    for k, r in sorted(res.items()):
        hit = boundary(r["title"], r.get("biz"))
        if hit:
            p, cl, sb = hit
            g = pat[p]
            g[0] += 1
            g[1] += r["class"] == cl
            g[2] += r["class"] == cl and r["sub"] == sb
            if (r["class"], r["sub"]) != (cl, sb):
                pat_bad.append([p, ORG[r["board"]], k, f"{cl}/{sb}", f"{r['class']}/{r['sub']}", r["title"][:50]])
        elif k in ref:
            out_n += 1
            out_ok += r["class"] == ref[k]["class"]
    pat_all = [sum(pat[p][i] for p in pat) for i in range(3)]
    t5 = table(["패턴", "건수", "class 일치", "class+sub 일치(준수)"],
               [[p, pat[p][0], pct(pat[p][1], pat[p][0]), pct(pat[p][2], pat[p][0])] for p in ("B1", "B2", "B3")]
               + [["**합계**", pat_all[0], pct(pat_all[1], pat_all[0]), f"**{pct(pat_all[2], pat_all[0])}**"]])
    t5b = table(["패턴", "기관", "ann_id", "기대", "이번", "제목"], pat_bad) if pat_bad else "없음"

    # 두 실행 비교
    cmp_md, rep = "", None
    if a.compare:
        other = {r["ann_id"]: r for r in map(json.loads, (Path(a.compare) / "results.jsonl").read_text(encoding="utf-8").splitlines()) if r}
        both = sorted(set(res) & set(other))
        c1 = sum(res[k]["class"] == other[k]["class"] for k in both)
        c2 = sum(res[k]["class"] == other[k]["class"] and res[k]["sub"] == other[k]["sub"] for k in both)
        rep = c1 / len(both) if both else None
        cdiff = [[ORG[res[k]["board"]], k, other[k]["class"] + "/" + other[k]["sub"], res[k]["class"] + "/" + res[k]["sub"], res[k]["title"][:50]]
                 for k in both if res[k]["class"] != other[k]["class"]]
        cmp_md = f"""
## 8. 다른 실행과 비교 (`{Path(a.compare).name}`)

- 공통 공고 {len(both)}건 · 이번에만 {len(set(res) - set(other))} · 저쪽에만 {len(set(other) - set(res))}
- class 일치 {pct(c1, len(both))} · class+sub 일치 {pct(c2, len(both))}

{table(["기관", "ann_id", "저쪽", "이번", "제목"], cdiff) if cdiff else "class가 달라진 공고 없음"}
"""

    # 관문 1(00 8장). 형식은 이 실행 기준, 재현성은 --compare가 있을 때만 판정한다
    fmt_ok = tot["missing"] == 0 and tot["bad_sub"] == 0 and tot["failed_calls"] == 0
    gate = [
        ["형식(빠짐·sub 불일치·실패 0)", "0", f"{tot['missing']}·{tot['bad_sub']}·{tot['failed_calls']}", "통과" if fmt_ok else "미달"],
        ["경계 규칙 준수", "≥ 95%", pct(pat_all[2], pat_all[0]), "통과" if pat_all[0] and pat_all[2] / pat_all[0] >= 0.95 else "미달"],
        ["경계 밖 기준 대비 class 일치", "≥ 98.5%", pct(out_ok, out_n), "통과" if out_n and out_ok / out_n >= 0.985 else "미달"],
        ["재현성(두 실행 class 일치)", "≥ 99%", f"{rep * 100:.1f}%" if rep is not None else "--compare 없음",
         "-" if rep is None else "통과" if rep >= 0.99 else "미달"],
    ]
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

## 7. 경계 규칙 (00 부록 E.1)

{t5}

- 패턴 밖 공고의 기준 대비 class 일치: {pct(out_ok, out_n)}

어긋난 공고:

{t5b}
{cmp_md}
## 9. 관문 1 판정

{table(["기준", "값", "이번", "판정"], gate)}
"""
    (run / "report.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()

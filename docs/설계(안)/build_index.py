"""설계(안)/docs/*.md → index.html

    python build_index.py

md 문서가 원본이고 index.html은 생성물이다. 실행할 때 다음을 점검해 경고한다.
  · 머리말(doc_id·title·group·version·status·updated) 누락
  · 기능 ID(F-XXX-NN) 중복
  · 문서의 현재 버전이 개정 이력(D-90)에 없음
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE / "docs"
TEMPLATE = HERE / "_template.html"
OUT = HERE / "index.html"
REQUIRED = ["doc_id", "title", "group", "version", "status", "updated"]
GROUP_ORDER = ["설계", "기능정의서", "데이터·검증", "관리"]


def parse_doc(path):
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    return meta, body


def table_rows(body):
    """md 본문의 표를 [(헤더, [행...]), ...]로 돌려준다."""
    tables, lines = [], body.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|\s*:?-{3,}", lines[i + 1]):
            head = split_row(lines[i])
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            tables.append((head, rows))
        else:
            i += 1
    return tables


def split_row(line):
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in cells]


def collect(rows_of, pattern, docs):
    out = []
    for d in docs:
        for head, rows in table_rows(d["body"]):
            for r in rows:
                if r and re.fullmatch(pattern, r[0]):
                    out.append({"doc": d["meta"]["doc_id"], **dict(zip(head, r))})
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    docs, warnings = [], []
    for p in sorted(DOCS.glob("*.md")):
        meta, body = parse_doc(p)
        miss = [k for k in REQUIRED if not meta.get(k)]
        if miss:
            warnings.append(f"{p.name}: 머리말 누락 {miss}")
            meta.setdefault("doc_id", p.stem)
            meta.setdefault("title", p.stem)
            meta.setdefault("group", "관리")
        docs.append({"file": p.name, "meta": meta, "body": body})

    functions = collect(None, r"F-[A-Z]{3}-\d{2}", docs)
    for fid, n in Counter(f["ID"] for f in functions).items():
        if n > 1:
            warnings.append(f"기능 ID 중복: {fid} ({n}회)")
    issues = collect(None, r"I-\d{2}", docs)
    decisions = collect(None, r"ADR-\d{3}", docs)
    history = next((d for d in docs if d["meta"].get("doc_id") == "D-90"), None)
    changes = []
    if history:
        for head, rows in table_rows(history["body"]):
            if "버전" in head:
                changes = [dict(zip(head, r)) for r in rows]
    logged = {(c.get("문서"), c.get("버전")) for c in changes}
    for d in docs:
        key = (d["meta"].get("doc_id"), d["meta"].get("version"))
        if key not in logged:
            warnings.append(f"{d['file']}: 버전 {key[1]}이 개정 이력에 없음")

    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    docs.sort(key=lambda d: (order.get(d["meta"].get("group"), 99), d["file"]))
    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "groups": GROUP_ORDER, "docs": docs, "functions": functions,
        "issues": issues, "decisions": decisions, "changes": changes, "warnings": warnings,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", r"<\/")
    OUT.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload), encoding="utf-8")
    print(f"index.html 생성 — 문서 {len(docs)}개 · 기능 {len(functions)}개 · 미결 {len(issues)}건 · 결정 {len(decisions)}건")
    for w in warnings:
        print("  경고:", w)


if __name__ == "__main__":
    main()

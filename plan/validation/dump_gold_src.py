"""정답표 원문 준비 — 표본 45건(00 부록 E.2)의 본문과 첨부 글자를 data/validation/gold-src/<ann_id>/ 에 쓴다.

사용: python plan/validation/dump_gold_src.py [--out data/validation/gold-src] [--timeout 120]
- 표본: docs/핸드오프/상세화면_표준필드_20261124.md 부록 A의 40건(게시판·게시물 번호)
        + NIA에서 기준 분류(.team/out/classification.jsonl)가 공모지원사업이고 첨부가 있는 최신 5건
- 첨부는 kordoc CLI(4.24.59, OCR 끔)로 읽는다. zip은 풀어서 안의 문서를 읽는다. 이미지 파일은 읽지 않는다(OCR 필요)
- 공고별 폴더: meta.json, body.txt(연락처 가림), att-<순번>[-<zip 안 번호>].md, attachments.json(파일별 읽기 결과)
- 표본 ann_id 목록은 plan/validation/gold/gold_notes.md 에 쓴다
DB는 읽기 전용으로 연다. 네트워크는 kordoc 패키지를 처음 받을 때(npx)만 쓴다.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.services.mask import mask_contacts  # noqa: E402

KORDOC = "kordoc@4.24.59"
DOC_EXT = {"hwp", "hwpx", "pdf", "docx", "xlsx"}
HANDOFF = ROOT / "docs" / "핸드오프" / "상세화면_표준필드_20261124.md"
REF = ROOT / ".team" / "out" / "classification.jsonl"
NOTES = ROOT / "plan" / "validation" / "gold" / "gold_notes.md"


def sample_posts():
    """부록 A 표 → [(게시판, 게시물 번호)]"""
    text = HANDOFF.read_text(encoding="utf-8")
    part = text[text.index("## 부록 A"):]
    out = []
    for board, nums in re.findall(r"^\|\s*([a-z_]+)\s*\|\s*([\d,\s]+)\|", part, re.M):
        out += [(board, n.strip()) for n in nums.split(",") if n.strip()]
    return out


def _kill_tree(p):
    """시간을 넘긴 kordoc을 자식 프로세스까지 끝낸다(Windows의 npx.cmd는 node 자식을 남긴다)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        os.killpg(p.pid, 9)


def kordoc(path, out_md, timeout):
    npx = shutil.which("npx") or "npx"
    p = subprocess.Popen([npx, "-y", KORDOC, str(path), "-o", str(out_md)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         start_new_session=os.name != "nt")
    try:
        _, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        p.communicate()
        out_md.unlink(missing_ok=True)
        return "timeout"
    if p.returncode != 0 or not out_md.exists():
        lines = err.decode("utf-8", "replace").strip().splitlines()
        return "fail:" + (lines[-1][:200] if lines else f"exit {p.returncode}")
    return f"ok:{len(out_md.read_text(encoding='utf-8', errors='replace'))}자"


def read_attachment(att, att_dir, dest, timeout):
    """첨부 하나 → [{name, inner, status, md}]"""
    src = att_dir / att["file_path"]
    ext = (att["ext"] or "").lower()
    base = f"att-{att['seq']:02d}"
    if ext == "zip":
        res = []
        with tempfile.TemporaryDirectory() as tmp:
            try:
                with zipfile.ZipFile(src) as z:
                    names = [i for i in z.infolist() if not i.is_dir()]
                    for k, info in enumerate(names, 1):
                        # zip 안 이름은 cp437로 읽히는 경우가 많아 cp949로 되돌린다
                        name = info.filename
                        if not info.flag_bits & 0x800:
                            try:
                                name = name.encode("cp437").decode("cp949")
                            except (UnicodeEncodeError, UnicodeDecodeError):
                                pass
                        iext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                        if iext not in DOC_EXT:
                            res.append({"name": att["name"], "inner": name, "status": "skip:형식"})
                            continue
                        f = Path(tmp) / f"{k:02d}.{iext}"
                        f.write_bytes(z.read(info))
                        md = dest / f"{base}-{k:02d}.md"
                        res.append({"name": att["name"], "inner": name, "status": kordoc(f, md, timeout), "md": md.name})
            except zipfile.BadZipFile:
                res.append({"name": att["name"], "status": "fail:zip 아님"})
        return res
    if ext not in DOC_EXT:
        return [{"name": att["name"], "status": "skip:형식"}]
    md = dest / f"{base}.md"
    return [{"name": att["name"], "status": kordoc(src, md, timeout), "md": md.name}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "validation" / "gold-src"))
    ap.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args()
    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'gongmo.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    att_dir = ROOT / "data" / "attachments"
    q = ("SELECT a.*, b.code AS board FROM announcements a JOIN boards b ON b.board_id = a.board_id "
         "WHERE b.code = ? AND a.post_no = ?")
    picks, missing = [], []
    for board, post_no in sample_posts():
        r = conn.execute(q, (board, post_no)).fetchone()
        (picks.append((r, "부록 A")) if r else missing.append(f"{board}/{post_no}"))
    ref = [json.loads(l) for l in REF.read_text(encoding="utf-8").splitlines() if l.strip()]
    have = {(r["board"], r["post_no"]) for r, _ in picks}
    nia = sorted((x for x in ref if x["board"] == "nia_bid" and x["class"] == "공모지원사업"), key=lambda x: x["posted"], reverse=True)
    extra = 0
    for x in nia:
        if extra == 5:
            break
        if ("nia_bid", x["post_no"]) in have:
            continue
        r = conn.execute(q, ("nia_bid", x["post_no"])).fetchone()
        if r and conn.execute("SELECT 1 FROM attachments WHERE ann_id = ? AND file_path IS NOT NULL", (r["ann_id"],)).fetchone():
            picks.append((r, "NIA 공모지원사업 최신"))
            extra += 1
    refmap = {(x["board"], x["post_no"]): x for x in ref}
    out = Path(a.out)
    rows = []
    for r, why in picks:
        dest = out / str(r["ann_id"])
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        b = refmap.get((r["board"], r["post_no"]), {})
        meta = {k: r[k] for k in ("ann_id", "board", "post_no", "title", "biz", "site_status", "period_raw", "start_at", "end_at",
                                  "posted_at", "list_date", "url")}
        meta.update({"ref_class": b.get("class"), "ref_sub": b.get("sub"), "why": why})
        (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (dest / "body.txt").write_text(mask_contacts(r["body"] or ""), encoding="utf-8")
        results = []
        for att in conn.execute("SELECT * FROM attachments WHERE ann_id = ? ORDER BY seq", (r["ann_id"],)):
            if not att["file_path"]:
                results.append({"name": att["name"], "status": "skip:파일 없음(" + (att["download_error"] or "받지 않음") + ")"})
                continue
            results += read_attachment(att, att_dir, dest, a.timeout)
        (dest / "attachments.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        ok = sum(x["status"].startswith("ok") for x in results)
        rows.append([r["ann_id"], r["board"], r["post_no"], b.get("class") or "-", why, f"{ok}/{len(results)}", (r["title"] or "")[:40]])
        print(f"{r['ann_id']} {r['board']}/{r['post_no']} 첨부 {ok}/{len(results)}", flush=True)
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    head = ["ann_id", "게시판", "게시물 번호", "기준 분류", "고른 이유", "첨부 읽음", "제목"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, x)) + " |" for x in rows]
    NOTES.write_text(f"""# 정답표 표본 (00 부록 E.2)

- 만든 명령: `python plan/validation/dump_gold_src.py` → 원문은 `data/validation/gold-src/<ann_id>/`(git 제외)
- 표본 {len(rows)}건 (부록 A {sum(1 for _, w in picks if w == '부록 A')}건 + NIA 공모지원사업 최신 {extra}건)
- ann_id는 이 PC에서 다시 수집한 DB 기준이다. 게시판·게시물 번호로 대조한다
- 부록 A에 있으나 DB에 없는 공고: {', '.join(missing) if missing else '없음'}

{chr(10).join(lines)}
""", encoding="utf-8")
    print(f"표본 {len(rows)}건 · 없음 {len(missing)}건 → {NOTES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

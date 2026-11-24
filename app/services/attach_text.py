"""본문이 짧은 공고의 첨부 공고문을 받아 글자를 뽑아 둔다.

흐름: 대상 공고 고르기 → 공고문으로 보이는 첨부 고르기 → (없으면) 내려받기 → 글자 추출 → attachments 에 저장.
- 대상: 본문이 짧은(기본 200자 미만) 공고 중 읽을 수 있는 첨부(HWP·HWPX·PDF·DOCX)가 있고 아직 읽지 않은 것.
- 신청서·동의서 같은 서식 파일은 건너뛰고, 공고·모집·안내 같은 이름의 파일을 먼저 읽는다.
- 이미지·압축 파일은 읽지 않는다.
"""
import re
from collections import defaultdict
from pathlib import Path

from ..crawler.utils import now_iso
from . import extract

FORM_WORDS = re.compile(r"양식|서식|신청서|동의서|서약서|확약서|위임장|체크리스트|별지|참가신청|이력서|개인정보|증빙|확인서|견적")
NOTICE_WORDS = re.compile(r"공고|모집|공모|안내|계획|요강|지침|사업|과업|제안요청")


def _score(name, ext):
    sc = 1 if ext in ("hwp", "hwpx", "pdf") else 0
    if NOTICE_WORDS.search(name or ""):
        sc += 3
    if FORM_WORDS.search(name or ""):
        sc -= 4
    return sc


def pick_files(rows, limit=3):
    """공고 1건의 첨부 목록(dict: seq, name, ext)에서 읽을 파일을 고른다. 서식으로 보이는 파일은 다른 후보가 없을 때만 1개."""
    cand = [r for r in rows if (r["ext"] or "").lower() in extract.SUPPORTED]
    cand.sort(key=lambda r: (-_score(r["name"], (r["ext"] or "").lower()), r["seq"]))
    good = [r for r in cand if _score(r["name"], (r["ext"] or "").lower()) > -3]
    return (good or cand[:1])[:limit]


def targets(conn, cfg, since=None, board_code=None, limit=None, ann_ids=None, redo=False):
    """읽을 공고 번호 목록(게시일 최신순). 본문이 짧은 공고만 대상이며, ann_ids 를 주면 그 공고는 본문 길이와 상관없이 읽는다."""
    short = cfg.get("ATTACH_TEXT_MIN_BODY", 200)
    sql = ("SELECT a.ann_id, length(coalesce(a.body, '')) AS n FROM announcements a JOIN boards b ON b.board_id=a.board_id WHERE 1=1")
    args = []
    if ann_ids:
        sql += f" AND a.ann_id IN ({','.join('?' * len(ann_ids))})"
        args += list(ann_ids)
    if since:
        sql += " AND a.posted_at >= ?"
        args.append(since)
    if board_code:
        sql += " AND b.code = ?"
        args.append(board_code)
    sql += " ORDER BY a.posted_at DESC, a.ann_id DESC"
    out = []
    for r in conn.execute(sql, args).fetchall():
        if not ann_ids and r["n"] >= short:
            continue
        atts = [dict(x) for x in conn.execute("SELECT seq, name, ext, file_path, text_status FROM attachments WHERE ann_id=? ORDER BY seq", (r["ann_id"],))]
        picked = pick_files(atts, cfg.get("ATTACH_TEXT_FILES", 3))
        if not picked:
            continue
        if not redo and any(p["text_status"] for p in picked):
            continue                                    # 이미 읽어 본 공고
        out.append(r["ann_id"])
        if limit and len(out) >= limit:
            break
    return out


def _board_of(conn, ann_id):
    return conn.execute("SELECT b.code FROM announcements a JOIN boards b ON b.board_id=a.board_id WHERE a.ann_id=?", (ann_id,)).fetchone()[0]


def process(conn, cfg, ann_ids, download=True, echo=True, say=print):
    """대상 공고의 첨부를 (필요하면) 받고 글자를 뽑아 저장한다. → 요약 dict"""
    from ..crawler.runner import fetch_attachments
    plan = {}
    for aid in ann_ids:
        rows = [dict(x) for x in conn.execute("SELECT seq, name, ext, file_path FROM attachments WHERE ann_id=? ORDER BY seq", (aid,))]
        plan[aid] = pick_files(rows, cfg.get("ATTACH_TEXT_FILES", 3))
    got = 0
    if download:
        by_board = defaultdict(dict)
        for aid, files in plan.items():
            need = {f["seq"] for f in files if not f["file_path"]}
            if need:
                by_board[_board_of(conn, aid)][aid] = need
        for code, only in by_board.items():
            got += fetch_attachments(conn, cfg, code, echo=echo, only=only)
    stat = defaultdict(int)
    for aid, files in plan.items():
        for f in files:
            row = conn.execute("SELECT file_path FROM attachments WHERE ann_id=? AND seq=?", (aid, f["seq"])).fetchone()
            if not row or not row["file_path"]:
                stat["파일 없음"] += 1
                continue
            text, status = extract.extract_text(Path(cfg["ATTACHMENT_DIR"]) / row["file_path"], f["ext"])
            try:
                conn.execute("UPDATE attachments SET text_body=?, text_status=?, text_at=? WHERE ann_id=? AND seq=?",
                             (text if status == "ok" else None, status, now_iso(), aid, f["seq"]))
            except Exception as e:  # noqa: BLE001 — 저장 못 하는 파일 하나가 전체를 멈추지 않게 상태만 남긴다
                status = f"error:저장 실패 {type(e).__name__}"
                conn.execute("UPDATE attachments SET text_body=NULL, text_status=?, text_at=? WHERE ann_id=? AND seq=?",
                             (status, now_iso(), aid, f["seq"]))
            stat[status.split(":")[0]] += 1
        conn.commit()
    return {"공고": len(plan), "내려받음": got, **dict(stat)}

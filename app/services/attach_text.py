"""본문이 짧은 공고의 첨부 공고문을 받아 글자를 뽑아 둔다.

흐름: 대상 공고 고르기 → 공고문으로 보이는 첨부 고르기 → (없으면) 내려받기 → 글자 추출 → attachments 에 저장.
- 대상: 본문이 짧은(기본 200자 미만) 공고 중 읽을 수 있는 첨부(HWP·HWPX·PDF·DOCX)가 있고 아직 읽지 않은 것.
- 신청서·동의서 같은 서식 파일은 건너뛰고, 공고·모집·안내 같은 이름의 파일을 먼저 읽는다.
- 글자는 kordoc을 먼저 쓰고, 실패하면 기존 추출기로 읽는다(ADR-050). 읽은 방법은 text_engine 에 남긴다.
- 같은 이름의 hwp/hwpx 가 있으면 pdf 는 고르지 않는다.
- zip 은 임시 폴더에 풀어 안의 공고문을 최대 2개 읽는다(부록 C.7). 이미지는 읽지 않는다.
"""
import re
import tempfile
import zipfile
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


ZIP_MAX_ENTRIES = 50
ZIP_FILES = 2
_HWP_FIRST = {"hwp": 0, "hwpx": 0}


def _stem(name):
    return re.sub(r"\.[^.]*$", "", (name or "").replace("\\", "/").rsplit("/", 1)[-1]).strip().lower()


def pick_files(rows, limit=3, readable=extract.SUPPORTED + ("zip",)):
    """공고 1건의 첨부 목록(dict: seq, name, ext)에서 읽을 파일을 고른다. 서식으로 보이는 파일은 다른 후보가 없을 때만 1개.
    같은 이름의 hwp/hwpx 가 있으면 pdf 는 빼고, 점수가 같으면 hwp/hwpx 를 먼저 읽는다."""
    cand = [r for r in rows if (r["ext"] or "").lower() in readable]
    hwp_stems = {_stem(r["name"]) for r in cand if (r["ext"] or "").lower() in _HWP_FIRST}
    cand = [r for r in cand if not ((r["ext"] or "").lower() == "pdf" and _stem(r["name"]) in hwp_stems)]
    cand.sort(key=lambda r: (-_score(r["name"], (r["ext"] or "").lower()), _HWP_FIRST.get((r["ext"] or "").lower(), 1), r["seq"]))
    good = [r for r in cand if _score(r["name"], (r["ext"] or "").lower()) > -3]
    return (good or cand[:1])[:limit]


def targets(conn, cfg, since=None, board_code=None, limit=None, ann_ids=None, redo=False, any_body=False):
    """읽을 공고 번호 목록(게시일 최신순). 본문이 짧은 공고만 대상이며, ann_ids 를 주거나 any_body=True 면 본문 길이와 상관없이 읽는다."""
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
        if not ann_ids and not any_body and r["n"] >= short:
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


def _zip_name(info):
    """UTF-8 표시(0x800)가 없는 이름은 cp437 로 읽힌 바이트를 cp949 로 다시 해석한다."""
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("cp949")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def _unsafe(name):
    n = name.replace("\\", "/")
    return n.startswith("/") or re.match(r"^[A-Za-z]:", n) is not None or ".." in n.split("/")


def read_zip(path, cfg):
    """zip 안의 공고문을 최대 ZIP_FILES 개 읽는다. → (텍스트, 상태, 엔진). 텍스트는 '### <안의 이름>' 머리를 붙여 잇는다."""
    cap = int(cfg.get("ATTACH_MAX_MB", 200) * 1024 * 1024)
    try:
        with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            rows, infos = [], {}
            for k, info in enumerate([i for i in z.infolist() if not i.is_dir()][:ZIP_MAX_ENTRIES], 1):
                name = _zip_name(info)
                if _unsafe(name):
                    continue
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                rows.append({"seq": k, "name": name, "ext": ext})
                infos[k] = info
            picked = pick_files(rows, ZIP_FILES, readable=extract.SUPPORTED)
            if not picked:
                return None, "unsupported", None
            parts, engine, status, used = [], None, "unsupported", 0
            for r in picked:
                info = infos[r["seq"]]
                if used + info.file_size > cap:
                    status = "error:zip 크기 상한 초과"
                    continue
                with z.open(info) as src:
                    data = src.read(cap - used + 1)          # 머리의 크기 표시를 믿지 않고 실제로 읽은 양으로 막는다
                if used + len(data) > cap:
                    status = "error:zip 크기 상한 초과"
                    continue
                used += len(data)
                f = Path(tmp) / f"{r['seq']:02d}.{r['ext']}"     # 안의 이름은 경로로 쓰지 않는다
                f.write_bytes(data)
                text, st, eng = extract.read_text(f, r["ext"], cfg)
                if st == "ok":
                    parts.append(f"### {r['name']}\n{text}")
                    engine = engine or eng
                elif not parts:
                    status = st
            if parts:
                return "\n\n".join(parts)[:extract.MAX_CHARS], "ok", engine
            return None, status, None
    except (zipfile.BadZipFile, OSError) as e:
        return None, f"error:{type(e).__name__}: {str(e)[:120]}", None


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
            src = Path(cfg["ATTACHMENT_DIR"]) / row["file_path"]
            if (f["ext"] or "").lower() == "zip":
                text, status, engine = read_zip(src, cfg)
            else:
                text, status, engine = extract.read_text(src, f["ext"], cfg)
            try:
                conn.execute("UPDATE attachments SET text_body=?, text_status=?, text_engine=?, text_at=? WHERE ann_id=? AND seq=?",
                             (text if status == "ok" else None, status, engine if status == "ok" else None, now_iso(), aid, f["seq"]))
            except Exception as e:  # noqa: BLE001 — 저장 못 하는 파일 하나가 전체를 멈추지 않게 상태만 남긴다
                status = f"error:저장 실패 {type(e).__name__}"
                conn.execute("UPDATE attachments SET text_body=NULL, text_status=?, text_engine=NULL, text_at=? WHERE ann_id=? AND seq=?",
                             (status, now_iso(), aid, f["seq"]))
            stat[status.split(":")[0]] += 1
        conn.commit()
    return {"공고": len(plan), "내려받음": got, **dict(stat)}

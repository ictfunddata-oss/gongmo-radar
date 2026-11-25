"""상세화면 표준 필드(ADR-045·051) — 공고 × 다섯 칸을 announcement_fields 에 둔다.

- load·context·input_hash: 2단계(코디네이터). targets·run: 4단계(부록 C.1·C.8).
- 원래 칸(announcements.period_raw·start_at·end_at·body)은 덮어쓰지 않는다(원칙 P4).
"""
import hashlib
import json

from .. import labels
from .model import FIELDS, Att, Doc

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

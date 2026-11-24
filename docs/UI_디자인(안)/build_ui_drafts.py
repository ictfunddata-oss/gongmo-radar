"""nipa.db → UI 디자인(안) 4종 + 목차 페이지 생성

    python build_ui_drafts.py

_template/*.html 의 /*__DATA__*/null 자리에 실데이터를, /*__COMMON__*/ 자리에 공통 스크립트를 넣는다.
분야·수혜자·공고유형 태그는 AI 분류 기능 구축 전까지 쓰는 '키워드 기반 임시 분류'다.
"""
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # 프로젝트 루트
DB_PATH = ROOT / "archive" / "legacy_nipa" / "data" / "nipa.db"
TARGETS = HERE.parent / "기획" / "ICT기금_전담기관_크롤링타겟_점검결과.xlsx"
TPL = HERE / "_template"
PAGES = ["index.html", "안1_운영현황판.html", "안2_공모사업찾기.html", "안3_마감일정.html", "안4_분석리포트.html"]

# ── 키워드 기반 임시 분류 (순서 = 우선순위) ──
KIND_RULES = [
    ("입찰·용역", r"입찰|용역|구매"),
    ("결과 발표", r"결과|대상자\s*선정|선정\s*(공고|안내|공지)|최종\s*선정"),
    ("설명회·안내", r"설명회|자료\s*게시|동영상|웨비나|유의사항|수요조사"),
    ("행사·전시 참가", r"전시|박람회|포럼|컨퍼런스|페스티벌|쇼케이스|파트너십|마켓|Summit|대회|포상"),
    ("입주 모집", r"입주|공유\s*오피스|공용공간|사무공간"),
]
FIELD_RULES = [
    ("인공지능", r"AI|인공지능|GPU|컴퓨팅|파운데이션|AX"),
    ("SW·SaaS", r"SW|소프트웨어|SaaS|오픈소스|공개SW"),
    ("클라우드", r"클라우드"),
    ("데이터", r"데이터"),
    ("XR·메타버스", r"XR|VR|AR|메타버스|가상융합|실감|디지털트윈|디지털 트윈"),
    ("디지털콘텐츠", r"콘텐츠|OTT|CG|스트리밍"),
    ("보안·안전", r"보안|안전"),
    ("네트워크·IoT", r"5G|IoT|네트워크|홈 서비스"),
    ("해외진출", r"해외|글로벌|하노이|호치민|싱가포르|인도|실리콘밸리|중동|UAE|베트남|ASEAN|수출"),
]
TARGET_RULES = [
    ("중소·벤처기업", r"중소|벤처|기업"),
    ("창업기업", r"창업|스타트업"),
    ("공공·지자체", r"지자체|지방자치|공공기관|광역|시·도|지역"),
    ("대학·병원·연구기관", r"대학|병원|연구기관|연구소"),
    ("협회·단체", r"협회|단체|컨소시엄"),
    ("개인·인재", r"개발자|인재|국민|청년|학생|교육생|누구나"),
]


def tags(rules, text, limit=None):
    out = [name for name, pat in rules if re.search(pat, text or "")]
    return out[:limit] if limit else out


def kind_of(title):
    for name, pat in KIND_RULES:
        if re.search(pat, title or ""):
            return name
    return "사업 모집"


def load_targets():
    wb = openpyxl.load_workbook(TARGETS, data_only=True)
    ws = wb.active
    orgs = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name, url, kind, verdict = row[0], row[1], row[2], row[3] or ""
        if not name:
            continue
        v = "가능" if "가능" in verdict else "불가" if "불가" in verdict else "보완"
        org = orgs.setdefault(name, {"name": name, "urls": []})
        org["urls"].append({"kind": re.sub(r"^Tier \d - ", "", kind or ""), "verdict": v, "url": url})
    for o in orgs.values():
        o["built"] = o["name"].startswith("정보통신산업진흥원")
    return list(orgs.values())


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    items = []
    for r in conn.execute("SELECT * FROM announcements ORDER BY id DESC"):
        title, body = r["title"] or "", r["body"] or ""
        text = f"{title} {r['biz'] or ''} {body[:1500]}"
        items.append({
            "id": r["id"], "title": title, "biz": r["biz"] or "", "start": r["start_at"], "end": r["end_at"],
            "posted": r["posted_at"] or r["list_date"], "views": r["views"] or 0, "files": r["attach_count"] or 0,
            "url": r["url"], "body_len": r["body_len"] or 0,
            "summary": re.sub(r"\s+", " ", body)[:160],
            "kind": kind_of(title),
            "changed": bool(re.search(r"수정|연장|재공고|추가\s*모집|추가모집|2차|3차", title)),
            "fields": tags(FIELD_RULES, f"{title} {r['biz'] or ''}", 3) or ["기타"],
            "targets": tags(TARGET_RULES, text, 3) or ["미상"],
        })
    runs = [dict(r) for r in conn.execute(
        "SELECT run_id, mode, started_at, ended_at, pages_total, pages_done, rows, new_rows, errors FROM runs ORDER BY started_at")]
    last = conn.execute("SELECT log FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    att = conn.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM attachments").fetchone()
    by_ext = dict(Counter(dict(conn.execute("SELECT ext, COUNT(*) FROM attachments GROUP BY ext").fetchall())).most_common())
    n = len(items)
    quality = {
        "작성일": sum(1 for x in items if x["posted"]),
        "사업구분": sum(1 for x in items if x["biz"]),
        "신청기간": sum(1 for x in items if x["start"]),
        "본문 50자 이상": sum(1 for x in items if x["body_len"] >= 50),
    }
    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "items": items, "runs": runs, "last_log": json.loads(last["log"] or "[]") if last else [],
        "attach": {"count": att[0], "bytes": att[1], "by_ext": by_ext},
        "quality": quality, "total": n, "orgs": load_targets(),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", r"<\/")
    common = (TPL / "common.js").read_text(encoding="utf-8")
    light = json.dumps({"total": n, "generated_at": data["generated_at"]}, ensure_ascii=False)
    for page in PAGES:
        html = (TPL / page).read_text(encoding="utf-8")
        html = html.replace("/*__COMMON__*/", common).replace("/*__DATA__*/null", light if page == "index.html" else payload)
        (HERE / page).write_text(html, encoding="utf-8")
        print("written", page)


if __name__ == "__main__":
    main()

"""엑셀 내보내기 — 공고·첨부 목록 2개 시트."""
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

ANN_SQL = """
SELECT o.name, b.name, a.post_no, a.title, a.biz, a.start_at, a.end_at, a.posted_at, a.views,
       a.attach_count, a.url, a.first_seen, a.last_seen, coalesce(l.class, '미분류'), l.sub
FROM announcements a
JOIN boards b ON b.board_id = a.board_id JOIN orgs o ON o.org_id = b.org_id
LEFT JOIN announcement_labels l ON l.ann_id = a.ann_id
ORDER BY a.posted_at DESC, a.ann_id DESC
"""
ANN_HEAD = ["기관", "게시판", "게시물번호", "제목", "사업구분", "신청시작", "신청마감", "게시일", "조회수",
            "첨부수", "원문URL", "최초수집", "최종수집", "유형", "하위유형"]   # 유형은 기존 열 뒤에 붙여 열 순서를 바꾸지 않는다
ATT_SQL = """
SELECT b.name, a.post_no, t.seq, t.name, t.ext, t.size_text, t.file_path, t.downloaded_at, t.download_error
FROM attachments t JOIN announcements a ON a.ann_id = t.ann_id JOIN boards b ON b.board_id = a.board_id
ORDER BY a.posted_at DESC, t.ann_id, t.seq
"""
ATT_HEAD = ["게시판", "게시물번호", "순번", "파일명", "확장자", "크기", "저장경로", "저장일시", "저장오류"]


def export_xlsx(conn, out_dir):
    wb = openpyxl.Workbook()
    for i, (title, head, sql) in enumerate((("공고", ANN_HEAD, ANN_SQL), ("첨부파일", ATT_HEAD, ATT_SQL))):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append(head)
        for r in conn.execute(sql):
            ws.append(list(r))
        ws.freeze_panes = "A2"
        for c in range(1, len(head) + 1):
            ws.column_dimensions[get_column_letter(c)].width = 40 if head[c - 1] in ("제목", "파일명", "저장경로") else 14
    out = Path(out_dir) / f"공모사업_수집결과_{datetime.now():%Y%m%d_%H%M}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out

"""성과지표 정의서 엑셀 생성 — 실적치는 nipa.db·실행 기록·URL 점검 결과에서 계산

    python build_kpi_sheet.py
"""
import sqlite3
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = HERE / "data" / "nipa.db"
TARGETS = ROOT / "ICT기금_전담기관_크롤링타겟_점검결과.xlsx"
OUT = ROOT / "ICT기금_공모사업_크롤링_성과지표_정의서.xlsx"
BUILT = {"정보통신산업진흥원 (NIPA)"}  # 수집기 가동 기관

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
SUB_FILL = PatternFill("solid", fgColor="D9E1F2")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
NA_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def pct(n, d):
    """일반 반올림(사사오입)으로 소수 첫째 자리까지 — 1/16 = 6.25% → 6.3%"""
    if not d:
        return "-"
    v = (Decimal(n) * 100 / Decimal(d)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{v}%"


def write_table(ws, top, headers, rows, widths=None, center_cols=()):
    for j, h in enumerate(headers, 1):
        c = ws.cell(top, j, h)
        c.font, c.fill, c.alignment, c.border = Font(bold=True, color="FFFFFF"), HEAD_FILL, CENTER, BOX
    for i, row in enumerate(rows, top + 1):
        for j, v in enumerate(row, 1):
            c = ws.cell(i, j, v)
            c.border = BOX
            c.alignment = CENTER if j in center_cols else WRAP
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    return top + len(rows) + 1


def title(ws, text, sub):
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = sub
    ws["A2"].font = Font(color="595959", size=9)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(DB_PATH)
    q = lambda s: conn.execute(s).fetchall()

    # ── 근거 수치 계산 ──
    total, first_post, last_post = q("SELECT COUNT(*), MIN(posted_at), MAX(posted_at) FROM announcements")[0]
    nos = [r[0] for r in q("SELECT list_no FROM announcements")]
    site_max = max(nos)
    missing = sorted(set(range(1, site_max + 1)) - set(nos))
    dup = len(nos) - len(set(nos))
    runs = q("SELECT run_id, mode, started_at, ended_at, pages_done, pages_total, rows, new_rows, errors "
             "FROM runs ORDER BY started_at")
    run_rows = sum(r[6] for r in runs)
    run_err = sum(r[8] for r in runs)
    run_days = sorted({r[2][:10] for r in runs})
    biz_ok, per_ok, post_ok, always = q(
        "SELECT SUM(biz IS NOT NULL AND biz<>''), SUM(start_at IS NOT NULL), SUM(posted_at IS NOT NULL), "
        "SUM(period_raw LIKE '%상시%') FROM announcements")[0]
    short_body = q("SELECT COUNT(*) FROM announcements WHERE body_len < 50")[0][0]
    att_n, att_b = q("SELECT COUNT(*), SUM(size_bytes) FROM attachments")[0]
    full = [r for r in runs if r[1] == "full" and r[5] == r[4]]
    full_last = full[-1] if full else None
    yearly = q("SELECT substr(posted_at,1,4), COUNT(*), SUM(attach_count) FROM announcements GROUP BY 1 ORDER BY 1")
    y2026 = dict((y, n) for y, n, _ in yearly).get("2026", 0)
    ext = q("SELECT ext, COUNT(*) FROM attachments GROUP BY ext ORDER BY 2 DESC")

    tw = openpyxl.load_workbook(TARGETS).active
    url_rows = [r for r in tw.iter_rows(min_row=2, values_only=True) if r[1]]
    orgs = list(dict.fromkeys(r[0] for r in url_rows))
    n_org = len(orgs)
    ok_urls = [r for r in url_rows if str(r[3]).startswith("✅")]
    ok_orgs = list(dict.fromkeys(r[0] for r in ok_urls))
    asof = run_days[-1] if run_days else date.today().isoformat()

    wb = openpyxl.Workbook()

    # ── 시트1: 지표 정의서 ──
    ws = wb.active
    ws.title = "1.지표정의서"
    title(ws, "ICT기금 공모사업 파이프라인 — 성과지표 정의서",
          f"실적 기준일 {asof} · 근거: nipa/data/nipa.db(공고·첨부·실행 기록), {TARGETS.name} · "
          f"목표치(노란 칸)는 담당자 입력용")
    full_note = (f"전체 수집 {full_last[0]}: {full_last[4]}/{full_last[5]}페이지, {full_last[6]}건"
                 if full_last else "")
    rows = [
        [1, "크롤링", "수집 대상 기관 구축률",
         f"크롤링타겟 엑셀의 {n_org}개 기관 중 수집기가 가동 중인 기관 비율",
         f"가동 기관 수 ÷ {n_org} × 100", "크롤링타겟 엑셀, 기관별 실행 기록(runs)", "분기",
         f"{pct(len(BUILT), n_org)} ({len(BUILT)}/{n_org})", None,
         f"가동 기관: NIPA(사업공고). 지금 그대로 수집 가능한 URL은 {len(url_rows)}개 중 "
         f"{len(ok_urls)}개({len(ok_orgs)}개 기관) — 시트4 참고"],
        [2, "크롤링", "수집 완전성",
         "사이트 게시 건수 대비 DB 수집 건수", "수집 건수 ÷ 사이트 게시 건수 × 100",
         "announcements.list_no (사이트 목록 번호 1~N의 빠짐·중복 검사)", "월",
         f"{pct(total, site_max)} ({total}/{site_max})", None,
         f"빠진 번호 {len(missing)}건, 중복 {dup}건. 분모는 '게시판에 현재 남아 있는 글' 기준 — "
         "2023년·2024년 건수가 유난히 적어 NIPA 전체 공고로 표현하지 않음"],
        [3, "크롤링", "수집 성공률",
         "수집기가 처리한 공고 중 오류 없이 저장된 비율", "(처리 건수 − 오류 건수) ÷ 처리 건수 × 100",
         "runs.rows, runs.errors", "월",
         f"{pct(run_rows - run_err, run_rows)} ({len(runs)}회 실행·{run_rows}건 처리·오류 {run_err})", None,
         f"실행 기록 {len(run_days)}일치({', '.join(run_days)})뿐 — 실적으로 쓰려면 기간 누적 필요. {full_note}"],
        [4, "크롤링", "수집 적시성",
         "신규 공고를 게시 다음 날까지 수집한 비율",
         "(first_seen 날짜 − 작성일 ≤ 1일인 건수) ÷ 신규 수집 건수 × 100",
         "announcements.first_seen(처음 발견 시각), posted_at(작성일)", "월", "측정 전", None,
         f"사이트 작성일은 날짜만 있어 시간 단위 측정 불가 → '다음 날까지'로 정의. "
         f"{asof} 일괄 수집분 {total}건은 제외하고 이후 신규 수집분부터 측정"],
        [5, "추출", "핵심 항목 추출률",
         "사업구분·신청기간·작성일 추출 성공 비율", "항목별 추출 건수 ÷ 전체 건수 × 100",
         "announcements.biz / start_at / posted_at", "월",
         f"작성일 {pct(post_ok, total)}, 사업구분 {pct(biz_ok, total)} ({total - biz_ok}건 없음), "
         f"신청기간 {pct(per_ok, total)} (상시모집 {always}건 성공 처리 시 {pct(per_ok + always, total)})", None,
         f"신청기간 없는 {always}건은 사이트에 '상시모집'으로 표기됨 — 성공/실패 산정 기준 확정 필요"],
        [6, "선별", "비R&D 공모 선별 정확도",
         "AI의 'ICT기금 비R&D 사업공고' 판정이 담당자 판정과 일치하는 비율",
         "일치 건수 ÷ 검증 세트 건수 × 100", "검증 세트(담당자가 정답 표시 — 신규 구축 필요)", "반기",
         "측정 전 (기능 미구축)", None,
         f"본문 50자 미만 공고 {short_body}건({pct(short_body, total)}) — 내용이 첨부·이미지에 있어 "
         "첨부 파싱 없이는 정확도 저하 가능"],
        [7, "분류", "수혜자 유형 분류 정확도",
         "AI의 수혜자 유형 분류가 담당자 분류와 일치하는 비율",
         "일치 건수 ÷ 검증 세트 건수 × 100", "검증 세트(신규 구축 필요)", "반기",
         "측정 전 (기능 미구축)", None, "분류 체계(유형 목록) 확정 후 측정"],
        [8, "서비스", "공모정보 이용 실적",
         "PIMS 공모 페이지 조회 수·이용자 수", "월간 조회 수, 월간 고유 이용자 수",
         "PIMS 접속 로그", "월", "측정 전 (서비스 미오픈)", None, "PIMS 연계(실증 이후) 후 측정"],
    ]
    end = write_table(ws, 4, ["#", "단계", "지표명", "정의", "산식", "근거 데이터", "측정 주기",
                              f"현재 실적\n({asof})", "목표치\n(입력)", "비고·주의사항"], rows,
                      widths=[4, 8, 20, 30, 30, 30, 8, 30, 12, 50], center_cols=(1, 2, 7))
    for i in range(5, end):
        ws.cell(i, 9).fill = INPUT_FILL
        if str(ws.cell(i, 8).value).startswith("측정 전"):
            ws.cell(i, 8).fill = NA_FILL
        ws.cell(i, 3).font = Font(bold=True)
    ws.freeze_panes = "D5"

    # ── 시트2: 참고 실적 ──
    ws2 = wb.create_sheet("2.참고실적")
    title(ws2, "참고 실적 (지표 아님 · 현황 설명용)", f"기준일 {asof} · NIPA 사업공고 게시판 게시 기준")
    end = write_table(ws2, 4, ["항목", "값", "비고"], [
        ["NIPA 사업공고 수집 건수", f"{total}건", f"작성일 {first_post} ~ {last_post}"],
        ["2026년 공고", f"{y2026}건", "작성일 기준"],
        ["첨부 목록", f"{att_n:,}개 / {att_b / 1024 ** 3:.2f} GB", "목록만 저장, 파일 자체는 미저장(보류)"],
        ["전체 수집 소요시간", f"{total}건 {(_secs(full_last))}초" if full_last else "-", "요청 간격 0.3초"],
        ["지금 바로 수집 가능한 URL", f"{len(url_rows)}개 중 {len(ok_urls)}개 ({len(ok_orgs)}개 기관)",
         f"URL 점검 결과({TARGETS.name})"],
    ], widths=[28, 30, 50])
    end = write_table(ws2, end + 1, ["작성연도", "공고 수", "첨부 수"], [list(r) for r in yearly], center_cols=(1, 2, 3))
    write_table(ws2, end + 1, ["첨부 확장자", "파일 수", ""], [[e or "(없음)", n, ""] for e, n in ext], center_cols=(1, 2))

    # ── 시트3: 근거 — 실행 기록 ──
    ws3 = wb.create_sheet("3.근거_실행기록")
    title(ws3, "근거 데이터 — 수집기 실행 기록 (runs)", "지표 3(수집 성공률)의 원천 데이터")
    write_table(ws3, 4, ["실행 ID", "모드", "시작", "종료", "처리 페이지", "사이트 페이지", "처리 건수", "신규", "오류"],
                [list(r) for r in runs], widths=[22, 12, 20, 20, 11, 11, 10, 8, 8], center_cols=(2, 5, 6, 7, 8, 9))
    ws3.cell(len(runs) + 6, 1, "※ 첫 전체 수집(310건)은 마지막 페이지 판정 오류로 31/36페이지에서 종료 → 수정 후 재실행해 353건 확보").font = Font(size=9, color="595959")

    # ── 시트4: 근거 — 기관별 구축 현황 ──
    ws4 = wb.create_sheet("4.근거_기관현황")
    title(ws4, f"근거 데이터 — 대상 기관 {n_org}개 구축 현황", "지표 1(수집 대상 기관 구축률)의 원천 데이터")
    org_rows = []
    for i, o in enumerate(orgs, 1):
        mine = [r for r in url_rows if r[0] == o]
        org_rows.append([i, o, "가동" if o in BUILT else "미구축", len(mine),
                         " / ".join(f"{r[2]}: {r[3]}" for r in mine)])
    end = write_table(ws4, 4, ["#", "기관", "수집기", "URL 수", "URL별 점검 판정(유형: 판정)"], org_rows,
                      widths=[4, 32, 9, 7, 110], center_cols=(1, 3, 4))
    for i in range(5, end):
        if ws4.cell(i, 3).value == "가동":
            ws4.cell(i, 3).fill = PatternFill("solid", fgColor="C6EFCE")

    # ── 시트5: 근거 — 완전성·추출 검증 ──
    ws5 = wb.create_sheet("5.근거_검증")
    title(ws5, "근거 데이터 — 수집 완전성·항목 추출 검증", "지표 2·5의 원천 데이터")
    write_table(ws5, 4, ["검증 항목", "결과", "방법"], [
        ["사이트 목록 번호 범위", f"1 ~ {site_max}", "목록 첫 번째 열(번호)의 최댓값 = 사이트 게시 건수"],
        ["DB 수집 건수", total, "announcements 행 수"],
        ["빠진 번호", len(missing) if not missing else ", ".join(map(str, missing)), "1~N 중 DB에 없는 번호"],
        ["중복 번호", dup, "같은 번호가 두 번 이상 저장된 건수"],
        ["작성일 추출", f"{post_ok}/{total}", "상세 페이지 .infoDt"],
        ["사업구분 추출", f"{biz_ok}/{total}", "상세 페이지 .gdi1 .bluebox"],
        ["신청기간 추출", f"{per_ok}/{total} (+상시모집 {always})", "상세 페이지 .gdi2 → 시작·마감 일시"],
        ["본문 50자 미만", f"{short_body}/{total}", "상세 페이지 '내용' 칸 텍스트 길이"],
    ], widths=[22, 26, 60], center_cols=(2,))

    for sh in wb.worksheets:
        sh.sheet_view.showGridLines = False
        sh.page_setup.orientation = "landscape"
        sh.page_setup.fitToWidth = 1
        sh.sheet_properties.pageSetUpPr.fitToPage = True
        sh.page_setup.fitToHeight = 0
    wb.save(OUT)
    print(f"{OUT.name} 저장 · 시트 {len(wb.worksheets)}개")


def _secs(run):
    from datetime import datetime
    return int((datetime.fromisoformat(run[3]) - datetime.fromisoformat(run[2])).total_seconds())


if __name__ == "__main__":
    main()

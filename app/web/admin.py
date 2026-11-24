"""운영 확인 화면(/admin) — 수집 현황·통계·로그와 전체 공고."""
import json
import csv
import io
from datetime import datetime

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for

from ..db import get_db
from ..services import admin_stats, audit, raw_view, searches, visits
from ..automation import scheduler as autosch, settings as autos
from ..automation.pipeline import is_running
from ..crawler.adapters import ADAPTERS
from ..services.announcements import get_announcement, list_announcements, stats
from .attachments import send_attachment

bp = Blueprint("admin", __name__, url_prefix="/admin")
PAGE = 30
PERIODS = (7, 30, 90)


def _audit(action, target="", detail=""):
    """관리자가 바꾼 것을 운영 이력에 남긴다."""
    audit.log(get_db(), current_app.config["ADMIN_ID"], action, target, detail)


def _period():
    n = request.args.get("days", 30, type=int)
    return n if n in PERIODS else 30


@bp.get("/")
def index():
    q = request.args.get("q", "").strip() or None
    page = max(1, request.args.get("page", 1, type=int))
    total, rows = list_announcements(get_db(), q=q, limit=PAGE, offset=(page - 1) * PAGE)
    return render_template("admin/index.html", rows=rows, total=total, page=page, pages=max(1, -(-total // PAGE)),
                           q=q or "", stats=stats(get_db()))


@bp.get("/raw")
def raw():
    """수집한 원본 공고 전체."""
    structs = raw_view.attachment_structs(current_app.config["DATA_DIR"])
    f = {k: request.args.get(k, "").strip() for k in ("q", "board", "body", "struct", "year")}
    page = max(1, request.args.get("page", 1, type=int))
    total, rows = raw_view.list_raw(get_db(), structs.keys(), q=f["q"] or None, board=f["board"] or None, body=f["body"] or None,
                                    struct=f["struct"] or None, year=f["year"] or None, limit=PAGE, offset=(page - 1) * PAGE)
    for r in rows:
        r["struct"] = r["ann_id"] in structs
    qs = "&".join(f"{k}={v}" for k, v in f.items() if v)
    return render_template("admin/raw.html", rows=rows, total=total, page=page, pages=max(1, -(-total // PAGE)), f=f, qs=qs,
                           summary=raw_view.summary(get_db(), structs.keys()), years=raw_view.years(get_db()), n_struct=len(structs),
                           boards=list(ADAPTERS.items()))


@bp.get("/raw/<int:ann_id>")
def raw_detail(ann_id):
    d = raw_view.get_raw(get_db(), ann_id)
    if d is None:
        abort(404)
    return render_template("admin/raw_detail.html", d=d, st=raw_view.attachment_structs(current_app.config["DATA_DIR"]).get(ann_id),
                           back=request.args.get("back", ""))


@bp.get("/announcements/<int:ann_id>")
def detail(ann_id):
    item = get_announcement(get_db(), ann_id)
    if item is None:
        abort(404)
    return render_template("admin/detail.html", item=item)


# ── 자동화(ADR-038) ──
def _next_label(dt):
    return f"{dt:%m-%d}({autos.DAYS[dt.weekday()]}) {dt:%H:%M}" if dt else None



@bp.get("/automation")
def automation():
    """자동 실행 설정(예약 시각·요일·대상 게시판), 지금 실행, 실행 기록."""
    conn, cfg = get_db(), current_app.config
    s = autos.load(conn)
    runs = []
    for r in conn.execute("SELECT run_id, trigger, started_at, ended_at, status, summary, log FROM automation_runs ORDER BY run_id DESC LIMIT 15"):
        d = dict(r)
        d["summary"] = json.loads(d["summary"] or "{}")
        d["log"] = json.loads(d["log"] or "[]")
        runs.append(d)
    return render_template("admin/automation.html", s=s, boards=list(ADAPTERS.items()), days=autos.DAYS, nxt=_next_label(autos.next_run(s, datetime.now())),
                           running=is_running(conn), runs=runs, sched_here=autosch._started,
                           times=(s["times"] + ["", "", ""])[:3])


@bp.post("/automation/save")
def automation_save():
    f = request.form
    raw = {
        "enabled": f.get("enabled"), "days": f.getlist("days"), "times": [f.get("t1", ""), f.get("t2", ""), f.get("t3", "")],
        "boards": f.getlist("boards"), "pages": f.get("pages"),
        **{k: f.get(k) for k in ("attachments", "crawl")},
    }
    s, errs = autos.clean(raw, list(ADAPTERS))
    if errs:
        for e in errs:
            flash(e, "warn")
    else:
        autos.save(get_db(), s)
        _audit("자동화 설정 저장", detail="사용" if s["enabled"] else "꺼짐")
        flash("자동화 설정을 저장했습니다." + (" 다음 예약 시각부터 적용됩니다." if s["enabled"] else " 자동 실행은 꺼져 있습니다."), "ok")
    return redirect(url_for("admin.automation"))


@bp.post("/automation/run")
def automation_run():
    """저장된 설정의 단계대로 지금 한 번 실행한다(자동 실행 사용 여부와 상관없음)."""
    if autosch.run_in_background(dict(current_app.config), "수동(지금 실행)"):
        _audit("자동화 지금 실행")
        flash("실행을 시작했습니다. 진행 상황은 아래 실행 기록에서 새로고침하며 확인하세요.", "ok")
    else:
        flash("이미 실행 중입니다. 끝난 뒤 다시 시도하세요.", "warn")
    return redirect(url_for("admin.automation"))


@bp.get("/attachments/<int:ann_id>/<int:seq>")
def attachment(ann_id, seq):
    return send_attachment(ann_id, seq)


# ── 금칙어 관리(F-SVC-19) ──
def _banned_path():
    return current_app.config["BANNED_TERMS_PATH"]


@bp.get("/banned")
def banned():
    """'많이 찾는 검색어'에서 뺄 금칙어를 보고 고친다. ?test=검색어 로 걸리는지 점검한다."""
    path, cfg = _banned_path(), current_app.config
    lst = searches.banned_list(path)
    ents = searches.entries(path)
    test = request.args.get("test", "").strip()
    return render_template(
        "admin/banned.html", words=[e for e in ents if e["kind"] == "ban"], allows=[e for e in ents if e["kind"] == "allow"],
        recent=searches.recent_terms(get_db(), lst, cfg["PUBLIC_POPULAR_DAYS"], 50, cfg["PUBLIC_POPULAR_MIN"]),
        test=test, hit=searches.matches(lst, test) if test else [], days=cfg["PUBLIC_POPULAR_DAYS"], min_count=cfg["PUBLIC_POPULAR_MIN"],
        path=str(path))


@bp.post("/banned/add")
def banned_add():
    word, kind = request.form.get("word", ""), "allow" if request.form.get("kind") == "allow" else "ban"
    hits = searches.title_hits(get_db(), word) if kind == "ban" else 0
    if hits and not request.form.get("force"):
        flash(f"'{word.strip()}'은(는) 수집한 공고 제목 {hits}건에 들어 있어 정상 검색어를 가릴 수 있습니다. 그래도 추가하려면 '그래도 추가'를 체크하세요.", "warn")
    else:
        ok, msg = searches.add_entry(_banned_path(), word, kind)
        if ok:
            _audit("금칙어 추가" if kind == "ban" else "예외 단어 추가", word.strip())
        flash(msg, "ok" if ok else "warn")
    return redirect(url_for("admin.banned"))


@bp.post("/banned/remove")
def banned_remove():
    kind = "allow" if request.form.get("kind") == "allow" else "ban"
    ok, msg = searches.remove_entry(_banned_path(), request.form.get("word", ""), kind)
    if ok:
        _audit("금칙어 삭제" if kind == "ban" else "예외 단어 삭제", request.form.get("word", ""))
    flash(msg, "ok" if ok else "warn")
    return redirect(url_for("admin.banned"))


# ── 통계·로그(2026-11) ──
@bp.get("/dashboard")
def dashboard():
    """운영 통계 — 방문 수·검색·데이터 현황·최근 문제를 한 화면에서 본다. ?days=7|30|90"""
    conn, cfg, n = get_db(), current_app.config, _period()
    ser = visits.series(conn, n)
    banned = searches.banned_list(cfg["BANNED_TERMS_PATH"])
    return render_template(
        "admin/dashboard.html", n=n, periods_list=PERIODS, ser=ser, today=ser[-1], week=visits.totals(ser[-7:]), total=visits.totals(ser),
        devices=visits.devices(conn, n), top=visits.top_notices(conn, n, 10), ss=admin_stats.search_summary(conn, n),
        terms=admin_stats.search_terms(conn, n, banned, limit=10), zero_terms=admin_stats.search_terms(conn, n, banned, limit=10, only_zero=True),
        cov=admin_stats.coverage(conn), stats=stats(conn), problems=admin_stats.recent_problems(conn),
        visit_on=cfg["VISIT_LOG"], uniq_on=cfg["VISIT_UNIQUE"])


@bp.get("/searches")
def search_stats():
    """검색어 통계 — 많이 찾은 검색어, 결과가 없었던 검색어. ?days=7|30|90, ?zero=1(결과 없음만), ?format=csv"""
    conn, cfg, n = get_db(), current_app.config, _period()
    only_zero = request.args.get("zero") == "1"
    banned = searches.banned_list(cfg["BANNED_TERMS_PATH"])
    terms = admin_stats.search_terms(conn, n, banned, limit=500, only_zero=only_zero)
    if request.args.get("format") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["검색어", "검색 횟수", "결과 없음 횟수", "평균 결과 수", "마지막 검색", "금칙어"])
        for t in terms:
            w.writerow([t["term"], t["count"], t["zero"], round(t["avg_results"], 1), t["last"], "예" if t["banned"] else ""])
        _audit("검색어 CSV 내려받기", detail=f"최근 {n}일")
        return Response(chr(0xFEFF) + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=search_terms_{n}d.csv"})
    return render_template("admin/searches.html", n=n, periods_list=PERIODS, only_zero=only_zero, ss=admin_stats.search_summary(conn, n),
                           terms=terms[:100], shown=min(len(terms), 100), found=len(terms))


@bp.get("/logs")
def logs():
    """로그 관리 — 수집·자동 실행·운영 이력. ?t=crawl|auto|ai|audit, ?f=필터, ?page="""
    conn = get_db()
    tab = request.args.get("t", "crawl")
    if tab not in dict(admin_stats.LOG_TABS):
        tab = "crawl"
    page, f = max(1, request.args.get("page", 1, type=int)), request.args.get("f", "")
    off, actions = (page - 1) * PAGE, []
    if tab == "crawl":
        total, rows = admin_stats.crawl_runs(conn, PAGE, off, only_issue=(f == "issue"))
    elif tab == "auto":
        total, rows = admin_stats.auto_runs(conn, PAGE, off)
    else:
        total, rows, actions = admin_stats.audit_rows(conn, PAGE, off, action=f or None)
    return render_template("admin/logs.html", tab=tab, tabs=admin_stats.LOG_TABS, rows=rows, total=total, page=page,
                           pages=max(1, -(-total // PAGE)), f=f, actions=actions, problems=admin_stats.recent_problems(conn))

"""수요자 화면 — UI 시안 안2(docs/UI_디자인(안)/안2_공모사업찾기.html)를 옮긴 것."""
import json

from flask import Blueprint, abort, current_app, render_template, request, url_for
from markupsafe import Markup

from ..auth import is_admin
from ..db import get_db
from ..services import searches, visits
from ..services.public import public_item, public_items
from .attachments import send_attachment

bp = Blueprint("public", __name__)


# 목록 화면이 쓰지 않는 값(상세에서만 쓴다). 공고 수천 건을 한 번에 보내므로 뺀다
LIST_SKIP = {"pct", "span", "url"}


def _json_for_page(obj):
    """<script type="application/json"> 안에 넣을 JSON. 한글을 유니코드 이스케이프로 바꾸지 않아 크기가 3분의 1 수준이고, 태그를 닫는 문자는 막는다."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    for ch in ("<", ">", "&", chr(0x2028), chr(0x2029)):
        s = s.replace(ch, chr(92) + "u%04x" % ord(ch))
    return Markup(s)


@bp.after_request
def _count_visit(resp):
    """목록·상세 방문을 센다(관리자 통계). 집계에 실패해도 화면은 그대로 보여 준다."""
    cfg = current_app.config
    if (cfg["VISIT_LOG"] and request.method == "GET" and resp.status_code == 200 and request.endpoint in ("public.index", "public.detail")
            and not is_admin()):
        try:
            visits.record(get_db(), "detail" if request.endpoint == "public.detail" else "list", (request.view_args or {}).get("ann_id", 0),
                          request.headers.get("User-Agent", ""), request.remote_addr or "", cfg["SECRET_KEY"], unique=cfg["VISIT_UNIQUE"])
        except Exception:  # noqa: BLE001
            current_app.logger.exception("방문 집계 실패")
    return resp


@bp.get("/")
def index():
    items, total = public_items(get_db(), current_app.config)
    slim = [{k: v for k, v in x.items() if k not in LIST_SKIP} for x in items]
    cfg = current_app.config
    data_json = _json_for_page({
        "items": slim, "total": total, "showEnded": cfg["PUBLIC_SHOW_ENDED"],
        "soonDays": cfg["PUBLIC_SOON_DAYS"], "soonMax": cfg["PUBLIC_SOON_MAX"],
        "searchLog": url_for("public.search_log"), "detail": url_for("public.detail", ann_id=0)})
    return render_template("public/index.html", data_json=data_json, items=items, total=total,
                           popular=searches.top_terms(get_db(), cfg["PUBLIC_POPULAR_DAYS"], cfg["PUBLIC_POPULAR_MAX"], cfg["PUBLIC_POPULAR_MIN"],
                                                      banned=searches.banned_list(cfg["BANNED_TERMS_PATH"])))


@bp.post("/search-log")
def search_log():
    """화면이 보낸 검색어를 기록한다(F-SVC-18). 기록할 수 없는 값은 조용히 무시한다.
    결과 수는 화면 값(n)을 쓰지 않고 서버가 다시 세며, 0건이면 기록하지 않는다."""
    data = request.get_json(silent=True) or {}
    q = str(data.get("q", ""))
    if not q.strip() or len(q) > searches.RAW_MAX:
        return "", 204
    items, _ = public_items(get_db(), current_app.config)
    n = searches.count_hits(items, q)
    if n:
        searches.record(get_db(), q, n, banned=searches.banned_list(current_app.config["BANNED_TERMS_PATH"]))
    return "", 204


@bp.get("/notice/<int:ann_id>")
def detail(ann_id):
    item = public_item(get_db(), current_app.config, ann_id)
    if item is None:
        abort(404)
    return render_template("public/detail.html", x=item)


@bp.get("/notice/<int:ann_id>/files/<int:seq>")
def attachment(ann_id, seq):
    if public_item(get_db(), current_app.config, ann_id) is None:
        abort(404)
    return send_attachment(ann_id, seq)

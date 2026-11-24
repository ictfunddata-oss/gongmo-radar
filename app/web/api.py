"""JSON API."""
from flask import Blueprint, current_app, jsonify, request

from ..db import get_db
from ..services.announcements import get_announcement, list_announcements, stats
from ..services.public import public_items

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.get("/public/announcements")
def public_announcements():
    """수요자 화면과 같은 공고 목록."""
    items, total = public_items(get_db(), current_app.config)
    return jsonify({"total": total, "count": len(items), "items": items})


@bp.get("/announcements")
def announcements():
    limit = min(200, request.args.get("limit", 50, type=int))
    offset = max(0, request.args.get("offset", 0, type=int))
    total, rows = list_announcements(get_db(), q=request.args.get("q"), limit=limit, offset=offset)
    return jsonify({"total": total, "items": rows})


@bp.get("/announcements/<int:ann_id>")
def announcement(ann_id):
    item = get_announcement(get_db(), ann_id)
    return jsonify(item) if item else (jsonify({"error": "not found"}), 404)


@bp.get("/stats")
def api_stats():
    return jsonify(stats(get_db()))

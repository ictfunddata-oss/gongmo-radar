"""저장된 첨부파일 내려받기(수요자·관리자 화면 공용)."""
from pathlib import Path

from flask import abort, current_app, send_file

from ..db import get_db


def send_attachment(ann_id, seq):
    row = get_db().execute("SELECT file_path FROM attachments WHERE ann_id=? AND seq=?", (ann_id, seq)).fetchone()
    if row is None or not row["file_path"]:
        abort(404)
    root = Path(current_app.config["ATTACHMENT_DIR"]).resolve()
    path = (root / row["file_path"]).resolve()
    if root not in path.parents or not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name.split("_", 1)[-1])

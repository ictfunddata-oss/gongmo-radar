"""관리자 로그인(F-SVC-20) — 운영 화면(/admin)과 운영용 API(/api, 수요자용 공개 API 제외)를 로그인한 사람만 쓰게 한다.

- 비밀번호는 해시(`ADMIN_PASSWORD_HASH`)로만 저장하고 `.env`에 둔다. 해시가 없으면 운영 화면은 열리지 않는다(막힌 채로 안내).
- 로그인 정보는 서명된 세션 쿠키에 담고, `ADMIN_SESSION_HOURS` 뒤에는 다시 로그인해야 한다.
- 같은 접속 주소에서 10분 안에 5번 틀리면 10분 동안 로그인을 막는다(서버를 다시 켜면 초기화).
"""
import hmac
import secrets
import time
from pathlib import Path

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .services import audit

bp = Blueprint("auth", __name__, url_prefix="/admin")

MAX_FAILS, WINDOW = 5, 600
_FAILS = {}                      # 접속 주소 → 실패 시각 목록
OPEN_ENDPOINTS = {"api.public_announcements"}   # 로그인 없이 쓰는 공개 API


def configured():
    return bool(current_app.config.get("ADMIN_PASSWORD_HASH"))


def is_admin():
    return session.get("admin") is True and session.get("exp", 0) > time.time()


def safe_next(target):
    """로그인 뒤 돌아갈 주소 — 이 사이트의 /admin 아래 경로만 허용한다(다른 사이트로 보내는 것 방지)."""
    t = (target or "").strip()
    return t if t.startswith("/admin") and not t.startswith("//") and "\\" not in t and "://" not in t else url_for("admin.index")


def require_admin():
    """admin·api 블루프린트의 before_request. 통과하면 None, 막으면 응답을 돌려준다."""
    if request.endpoint in OPEN_ENDPOINTS or is_admin():
        return None
    wants_json = request.path.startswith("/api/")
    if not configured():
        if wants_json:
            return jsonify({"error": "admin password not set"}), 503
        return render_template("admin/login.html", unset=True), 503
    if wants_json:
        return jsonify({"error": "login required"}), 401
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))


def _locked(ip, now):
    recent = [t for t in _FAILS.get(ip, []) if now - t < WINDOW]
    _FAILS[ip] = recent
    return len(recent) >= MAX_FAILS


@bp.route("/login", methods=["GET", "POST"])
def login():
    nxt = request.values.get("next", "")
    if not configured():
        return render_template("admin/login.html", unset=True), 503
    if request.method == "GET":
        return render_template("admin/login.html", next=nxt, is_admin=is_admin())
    ip, now = request.remote_addr or "?", time.time()
    if _locked(ip, now):
        audit.log(get_db(), "(알 수 없음)", "로그인 차단", detail=f"접속 주소 {ip} — 실패 횟수 초과")
        return render_template("admin/login.html", next=nxt, error="로그인에 여러 번 실패해 잠시 막았습니다. 10분 뒤에 다시 시도해 주세요."), 429
    user_ok = hmac.compare_digest(request.form.get("id", "").strip(), current_app.config["ADMIN_ID"])
    pw_ok = check_password_hash(current_app.config["ADMIN_PASSWORD_HASH"], request.form.get("password", ""))
    if not (user_ok and pw_ok):
        _FAILS.setdefault(ip, []).append(now)
        typed = request.form.get("id", "").strip()
        audit.log(get_db(), typed if user_ok else "(다른 아이디)", "로그인 실패", detail=f"접속 주소 {ip}")
        time.sleep(0.4)          # 연속 대입 속도를 늦춘다
        return render_template("admin/login.html", next=nxt, error="아이디 또는 비밀번호가 맞지 않습니다."), 401
    _FAILS.pop(ip, None)
    session.clear()
    session["admin"], session["exp"] = True, now + current_app.config["ADMIN_SESSION_HOURS"] * 3600
    audit.log(get_db(), current_app.config["ADMIN_ID"], "로그인", detail=f"접속 주소 {ip}")
    return redirect(safe_next(nxt))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# ── 비밀번호 설정(CLI에서 사용) ──
def make_hash(password):
    return generate_password_hash(password)


def set_env(path, updates):
    """`.env`의 KEY=값 줄을 바꾸거나 없으면 끝에 추가한다. 다른 줄은 그대로 둔다."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    for key, value in updates.items():
        line = f"{key}={value}"
        for i, existing in enumerate(lines):
            if existing.split("=", 1)[0].strip() == key:
                lines[i] = line
                break
        else:
            lines.append(line)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def random_secret():
    return secrets.token_urlsafe(48)

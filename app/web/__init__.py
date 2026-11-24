"""웹 블루프린트 — public(수요자 화면, UI 시안 안2) · admin(운영 확인 화면) · api(JSON)."""
from ..auth import bp as auth_bp, require_admin
from .admin import bp as admin_bp
from .api import bp as api_bp
from .public import bp as public_bp

# 운영 화면과 운영용 API는 로그인한 관리자만. 수요자용 공개 API(api.public_announcements)만 예외(auth.OPEN_ENDPOINTS)
admin_bp.before_request(require_admin)
api_bp.before_request(require_admin)

BLUEPRINTS = (public_bp, auth_bp, admin_bp, api_bp)

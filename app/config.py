"""설정 — 프로젝트 루트의 .env 를 읽는다. 경로 값은 상대경로면 프로젝트 루트 기준으로 해석한다."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _path(name, default):
    raw = os.getenv(name, "").strip()
    p = Path(raw) if raw else Path(default)
    return p if p.is_absolute() else (BASE_DIR / p).resolve()


def _bool(name, default):
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else raw.strip().lower() in ("1", "true", "yes", "y", "on")


WEAK_SECRETS = {"", "dev-only-change-me", "change-me"}


def check_secret(cfg):
    """운영 진입점(wsgi.py)용 — SECRET_KEY가 비었거나 공개된 기본값이거나 32자보다 짧으면 멈춘다."""
    key = cfg.get("SECRET_KEY") or ""
    if key in WEAK_SECRETS or len(key) < 32:
        raise RuntimeError("SECRET_KEY가 비었거나 기본값이거나 32자보다 짧습니다. 운영 환경에는 임의의 긴 값을 넣으세요 "
                           "(예: python -c \"import secrets; print(secrets.token_hex(32))\").")


def load_config():
    data_dir = _path("DATA_DIR", "data")
    return {
        "SECRET_KEY": os.getenv("SECRET_KEY", "dev-only-change-me"),
        # 관리자 로그인(F-SVC-20) — 비밀번호는 해시로만 둔다. `flask --app run set-admin-password` 로 설정
        "ADMIN_ID": os.getenv("ADMIN_ID", "admin"),
        "ADMIN_PASSWORD_HASH": os.getenv("ADMIN_PASSWORD_HASH", "").strip(),
        "ADMIN_SESSION_HOURS": float(os.getenv("ADMIN_SESSION_HOURS", "8")),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",                                # 다른 사이트에서 온 POST 요청에는 쿠키를 보내지 않음
        "SESSION_COOKIE_SECURE": _bool("ADMIN_COOKIE_SECURE", False),   # https 로 배포할 때 켠다
        # 앞단 프록시(로드밸런서·nginx) 수. 0보다 크면 X-Forwarded-* 를 그만큼 믿어 접속 주소를 정한다
        "TRUSTED_PROXY_HOPS": int(os.getenv("TRUSTED_PROXY_HOPS", "0")),
        "DATA_DIR": data_dir,
        "DB_PATH": _path("DB_PATH", data_dir / "gongmo.db"),
        # 첨부 저장 경로 — 사용자가 .env 의 ATTACHMENT_DIR 로 임시 지정
        "ATTACHMENT_DIR": _path("ATTACHMENT_DIR", data_dir / "attachments"),
        "EXPORT_DIR": _path("EXPORT_DIR", data_dir / "exports"),
        "LEGACY_DB_PATH": _path("LEGACY_DB_PATH", "archive/legacy_nipa/data/nipa.db"),
        # 수집
        "CRAWL_DELAY": float(os.getenv("CRAWL_DELAY", "0.3")),
        "ROBOTS_CHECK": _bool("ROBOTS_CHECK", True),   # 수집 전 robots.txt 확인(0이면 건너뜀)
        "DOWNLOAD_ATTACHMENTS": _bool("DOWNLOAD_ATTACHMENTS", True),
        "ATTACH_MAX_MB": float(os.getenv("ATTACH_MAX_MB", "200")),
        # 첨부 글자 추출: 본문이 이보다 짧으면 읽기 대상, 공고 1건에서 읽는 첨부 파일 수
        "ATTACH_TEXT_MIN_BODY": int(os.getenv("ATTACH_TEXT_MIN_BODY", "200")),
        "ATTACH_TEXT_FILES": int(os.getenv("ATTACH_TEXT_FILES", "3")),
        # 자동화(ADR-038): 웹 서버가 예약 실행기를 함께 띄울지. 별도 서비스로 돌릴 때는 0
        "AUTOMATION_SCHEDULER": _bool("AUTOMATION_SCHEDULER", True),
        # 접수 마감 공고를 기본으로 보여 줄지
        "PUBLIC_SHOW_ENDED": _bool("PUBLIC_SHOW_ENDED", True),
        # 수요자 목록 화면의 작은 서비스(F-SVC-12~14)
        "PUBLIC_SOON_DAYS": int(os.getenv("PUBLIC_SOON_DAYS", "30")),   # 곧 마감 띠: 마감까지 남은 일수
        "PUBLIC_SOON_MAX": int(os.getenv("PUBLIC_SOON_MAX", "10")),     # 곧 마감 띠: 최대 건수
        "PUBLIC_NEW_DAYS": int(os.getenv("PUBLIC_NEW_DAYS", "7")),      # NEW 배지: 게시 후 일수
        # 많이 찾는 검색어(F-SVC-18)
        "PUBLIC_POPULAR_DAYS": int(os.getenv("PUBLIC_POPULAR_DAYS", "30")),   # 집계 기간(일)
        "PUBLIC_POPULAR_MAX": int(os.getenv("PUBLIC_POPULAR_MAX", "5")),      # 최대 표시 개수
        "PUBLIC_POPULAR_MIN": int(os.getenv("PUBLIC_POPULAR_MIN", "2")),      # 이 횟수 이상 검색된 것만 표시
        "VISIT_LOG": _bool("VISIT_LOG", True),                              # 수요자 화면 방문 수 집계(관리자 통계)
        "VISIT_UNIQUE": _bool("VISIT_UNIQUE", True),                        # 하루 단위 순방문 집계(끄면 조회 수만 센다)
        "BANNED_TERMS_PATH": _path("BANNED_TERMS_PATH", "app/banned_terms.txt"),   # 금칙어 목록(수정하면 바로 적용)
    }
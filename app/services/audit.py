"""운영 이력 — 관리자가 바꾼 것과 로그인 시도를 남긴다. 비밀번호·검색한 사람의 정보는 남기지 않는다."""
from datetime import datetime, timedelta

KEEP_DAYS = 365


def log(conn, actor, action, target="", detail="", now=None):
    """이력 1건을 남긴다. 실패해도 원래 작업을 막지 않는다."""
    now = now or datetime.now()
    try:
        conn.execute("INSERT INTO audit_logs(at, actor, action, target, detail) VALUES (?,?,?,?,?)",
                     (now.isoformat(timespec="seconds"), (actor or "")[:40], action[:40], str(target or "")[:200], str(detail or "")[:500]))
        conn.execute("DELETE FROM audit_logs WHERE at < ?", ((now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds"),))
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False

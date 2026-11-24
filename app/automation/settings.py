"""자동화 설정 — DB(app_kv)에 JSON으로 저장하고, 다음 실행 시각·실행할 시각(슬롯) 계산을 한다.

요일은 파이썬 규칙(월=0 … 일=6). 시각은 'HH:MM' 문자열. 서버의 현지 시각을 쓴다.
기본값은 '사용 안 함'이라 켜기 전에는 아무 일도 일어나지 않는다.
"""
import json
import re
from datetime import datetime, timedelta

KEY = "automation_settings"
KEY_LAST_SLOT = "automation_last_slot"
DAYS = ["월", "화", "수", "목", "금", "토", "일"]
MAX_TIMES = 6
GRACE_MIN = 60   # 예약 시각이 지난 뒤 이 시간 안에만 따라잡아 실행(서버가 꺼져 있던 동안의 옛 예약은 건너뜀)

DEFAULTS = {
    "enabled": False,
    "days": [0, 1, 2, 3, 4, 5, 6],
    "times": ["06:00"],
    "boards": None,            # None = 등록된 게시판 모두
    "pages": 0,                # 0 = 새 글이 없는 쪽에서 멈춤(권장), N = 앞 N쪽까지만
    "attachments": False,      # 첨부 파일 내려받기(기본 끔 — 이름만 저장)
    "crawl": True,             # 수집
}


def _hhmm(s):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", s or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def clean(raw, all_boards):
    """폼·저장값을 검증해 정리한다. → (설정 dict, 오류 문구 목록)"""
    errs, s = [], dict(DEFAULTS)
    s["enabled"] = bool(raw.get("enabled"))
    days = sorted({int(d) for d in raw.get("days", []) if str(d).isdigit() and 0 <= int(d) <= 6})
    s["days"] = days
    times = []
    for t in raw.get("times", []):
        if not str(t).strip():
            continue
        h = _hhmm(str(t))
        if h is None:
            errs.append(f"실행 시각 '{t}'은(는) 올바른 시각(예: 06:00)이 아닙니다.")
        elif h not in times:
            times.append(h)
    s["times"] = sorted(times)[:MAX_TIMES]
    boards = [b for b in raw.get("boards", []) if b in all_boards]
    s["boards"] = None if set(boards) == set(all_boards) else boards
    for k, lo, hi in (("pages", 0, 200),):
        try:
            v = int(raw.get(k, DEFAULTS[k]))
        except (TypeError, ValueError):
            errs.append(f"{k} 값이 숫자가 아닙니다.")
            continue
        s[k] = min(hi, max(lo, v))
    for k in ("attachments", "crawl"):
        s[k] = bool(raw.get(k))
    if s["enabled"] and not s["days"]:
        errs.append("자동 실행을 켜려면 요일을 하나 이상 선택하세요.")
    if s["enabled"] and not s["times"]:
        errs.append("자동 실행을 켜려면 실행 시각을 하나 이상 입력하세요.")
    if s["boards"] is not None and not s["boards"] and s["crawl"]:
        errs.append("수집할 게시판을 하나 이상 선택하세요.")
    return s, errs


def load(conn):
    row = conn.execute("SELECT value FROM app_kv WHERE key=?", (KEY,)).fetchone()
    s = dict(DEFAULTS)
    if row:
        try:
            s.update(json.loads(row[0]))
        except ValueError:
            pass
    return s


def save(conn, s):
    conn.execute("INSERT INTO app_kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (KEY, json.dumps(s, ensure_ascii=False)))
    conn.commit()


def slots_on(s, day):
    """그날의 예약 시각(datetime) 목록."""
    if day.weekday() not in s["days"]:
        return []
    return [datetime.combine(day.date(), datetime.strptime(t, "%H:%M").time()) for t in s["times"]]


def next_run(s, now):
    """다음 예약 시각. 자동 실행이 꺼져 있거나 요일·시각이 없으면 None."""
    if not s["enabled"]:
        return None
    for i in range(0, 9):
        for slot in slots_on(s, now + timedelta(days=i)):
            if slot > now:
                return slot
    return None


def due_slot(s, last_slot, now):
    """지금 실행해야 할 예약 시각(문자열 'YYYY-MM-DD HH:MM') 또는 None.
    last_slot 이후의 가장 늦은 예약 중, 지난 지 GRACE_MIN 분 이내인 것."""
    if not s["enabled"]:
        return None
    best = None
    for i in (0, -1):
        for slot in slots_on(s, now + timedelta(days=i)):
            if slot <= now and now - slot <= timedelta(minutes=GRACE_MIN) and (best is None or slot > best):
                best = slot
    if best is None:
        return None
    key = best.strftime("%Y-%m-%d %H:%M")
    return key if not last_slot or key > last_slot else None

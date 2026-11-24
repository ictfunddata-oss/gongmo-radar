import re
from datetime import datetime

_WIN_BAD = r'[<>:"/\\|?*\x00-\x1f]'


def sp(text):
    """연속 공백을 한 칸으로."""
    return re.sub(r"\s+", " ", text or "").strip()


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def parse_period(raw):
    """'2026-10-01 09:00 ~ 2026-10-30 13:00' → ('2026-10-01T09:00', '2026-10-30T13:00'). 날짜만 있으면 시각 생략."""
    found = re.findall(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?", raw or "")
    iso = [f"{d}T{t}" if t else d for d, t in found]
    return (iso[0] if iso else None, iso[1] if len(iso) > 1 else None)


def size_to_bytes(text):
    m = re.search(r"([\d.,]+)\s*(B|KB|MB|GB)", text or "", re.I)
    if not m:
        return 0
    mult = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[m.group(2).upper()]
    return int(float(m.group(1).replace(",", "")) * mult)


def safe_filename(name, limit=150):
    """Windows에서 쓸 수 없는 문자를 바꾸고 길이를 줄인다(확장자 유지)."""
    name = re.sub(_WIN_BAD, "_", sp(name)).strip(" .") or "file"
    if len(name) > limit:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: limit - len(ext) - 1] + "." + ext) if dot and len(ext) <= 10 else name[:limit]
    return name

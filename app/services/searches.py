"""검색어 기록과 '많이 찾는 검색어'(F-SVC-18).

- 이용자가 수요자 목록에서 직접 입력해 검색한 단어를 기록한다. 누가 검색했는지(IP·계정)는 저장하지 않는다.
- 이메일·전화번호처럼 보이는 값, 너무 짧거나 긴 값은 기록하지 않는다.
- 금칙어 목록(`app/banned_terms.txt`)에 걸리는 검색어는 기록하지 않고, 이미 기록된 것도 '많이 찾는 검색어'에서 뺀다.
- 검색 결과가 0건인 검색어는 '많이 찾는 검색어'에서 뺀다(눌러도 아무것도 안 나오므로).
"""
import re
from collections import Counter
from pathlib import Path
from datetime import datetime, timedelta

MIN_LEN, MAX_LEN = 2, 30
KEEP_DAYS = 180                       # 이보다 오래된 기록은 새 기록을 쓸 때 지운다
_PRIVATE = re.compile(r"@|\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{4}|https?://|www\.")


def _squash(text):
    """금칙어 검사용: 소문자로 바꾸고 한글·영문·숫자·자모만 남긴다(공백·기호로 단어를 쪼개 피하는 것을 막는다)."""
    return re.sub(r"[^0-9a-zㄱ-ㆎ가-힣]", "", (text or "").lower())


class BannedList:
    """금칙어 목록. 파일이 바뀌면 다음 검사 때 다시 읽는다. 줄 형식은 `app/banned_terms.txt` 맨 위 설명 참고."""

    def __init__(self, path=None, lines=None):
        self.path, self._mtime, self.words, self.allow = Path(path) if path else None, None, [], []
        if lines is not None:
            self._parse(lines)

    def _parse(self, lines):
        words, allow = [], []
        for line in lines:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            (allow if t.startswith("!") else words).append(_squash(t[1:] if t.startswith("!") else t))
        self.words = [w for w in words if w]
        self.allow = sorted((a for a in allow if a), key=len, reverse=True)   # 긴 예외부터 지운다

    def _refresh(self):
        if not self.path:
            return
        try:
            m = self.path.stat().st_mtime
            if m != self._mtime:
                self._parse(self.path.read_text(encoding="utf-8").splitlines())
                self._mtime = m
        except OSError:
            pass                      # 파일이 없거나 읽을 수 없으면 직전 목록을 그대로 쓴다

    def contains(self, term):
        """검색어에 금칙어가 들어 있으면 True. 예외 단어를 뺀 나머지로 검사한다."""
        self._refresh()
        t = _squash(term)
        for a in self.allow:
            t = t.replace(a, "")
        return any(w in t for w in self.words)


_LISTS = {}


def banned_list(path):
    """경로별로 목록을 한 번만 만들어 재사용한다."""
    key = str(path)
    if key not in _LISTS:
        _LISTS[key] = BannedList(path)
    return _LISTS[key]


def normalize(term):
    """연속 공백을 한 칸으로 줄이고 양끝을 자른다. 기록할 수 없는 값이면 ''."""
    t = re.sub(r"\s+", " ", term or "").strip()
    if not (MIN_LEN <= len(t) <= MAX_LEN) or _PRIVATE.search(t):
        return ""
    return t


def record(conn, term, results, now=None, banned=None):
    """검색어 1건을 기록한다. 기록했으면 True. 기록할 수 없는 값·금칙어는 저장하지 않는다."""
    t = normalize(term)
    if not t or (banned and banned.contains(t)):
        return False
    now = now or datetime.now()
    conn.execute("DELETE FROM search_logs WHERE searched_at < ?",
                 ((now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds"),))
    conn.execute("INSERT INTO search_logs(term, norm, results, searched_at) VALUES (?,?,?,?)",
                 (t, t.lower(), max(0, int(results or 0)), now.isoformat(timespec="seconds")))
    conn.commit()
    return True


def top_terms(conn, days=30, limit=5, min_count=2, now=None, banned=None):
    """최근 days일 동안 결과가 있었던 검색어를 많이 검색된 순으로 돌려준다. 대소문자는 구분하지 않고,
    화면에 보이는 표기는 가장 자주 쓰인 표기다. 같은 횟수면 최근에 검색된 것이 앞선다. → [(검색어, 횟수), ...]"""
    now = now or datetime.now()
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute("SELECT term, norm, searched_at FROM search_logs WHERE searched_at >= ? AND results > 0", (since,)).fetchall()
    count, last, forms = Counter(), {}, {}
    for r in rows:
        if banned and banned.contains(r["term"]):      # 목록이 나중에 늘어도 이미 쌓인 기록에서 바로 빠진다
            continue
        count[r["norm"]] += 1
        last[r["norm"]] = max(last.get(r["norm"], ""), r["searched_at"])
        forms.setdefault(r["norm"], Counter())[r["term"]] += 1
    ranked = [n for n, c in count.items() if c >= min_count]
    ranked.sort(key=lambda n: (-count[n], _neg(last[n])))
    return [(forms[n].most_common(1)[0][0], count[n]) for n in ranked[:limit]]


def _neg(s):
    """문자열 정렬을 내림차순으로 만들기 위한 키(최근 일시가 앞서도록)."""
    return tuple(-ord(c) for c in s)


# ── 금칙어 관리(관리자 화면) ──
MARK = "# ── 관리자 화면에서 추가 ──"


def _backup(path):
    p = Path(path)
    if p.exists():
        p.with_suffix(p.suffix + ".bak").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")


def entries(path):
    """목록 파일의 항목을 [{word, kind('ban'|'allow'), added(관리자 화면에서 추가한 것인지)}]로 돌려준다."""
    out, added = [], False
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t == MARK:
            added = True
        elif t and not t.startswith("#"):
            allow = t.startswith("!")
            out.append({"word": t[1:] if allow else t, "kind": "allow" if allow else "ban", "added": added})
    return out


def add_entry(path, word, kind="ban"):
    """금칙어(kind='ban') 또는 예외 단어(kind='allow')를 파일 끝의 관리자 구역에 추가한다. → (성공 여부, 메시지)"""
    w = re.sub(r"\s+", " ", word or "").strip().lstrip("!#").strip()
    key = _squash(w)
    if len(key) < 2:
        return False, "두 글자 이상(공백·기호 제외)으로 입력해 주세요."
    if len(w) > 30:
        return False, "30자 이하로 입력해 주세요."
    if any(e["kind"] == kind and _squash(e["word"]) == key for e in entries(path)):
        return False, f"이미 목록에 있는 단어입니다: {w}"
    p = Path(path)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    _backup(p)
    if MARK not in text:
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + MARK + "\n"
    elif not text.endswith("\n"):
        text += "\n"
    p.write_text(text + ("!" if kind == "allow" else "") + w + "\n", encoding="utf-8")
    return True, f"{'예외 단어' if kind == 'allow' else '금칙어'}로 추가했습니다: {w}"


def remove_entry(path, word, kind="ban"):
    """목록에서 단어를 지운다(같은 단어가 여러 줄이면 모두). 지우기 전 .bak 로 백업한다. → (성공 여부, 메시지)"""
    p = Path(path)
    key = _squash(word)
    kept, n = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and not t.startswith("#") and (t.startswith("!") == (kind == "allow")) and _squash(t.lstrip("!")) == key:
            n += 1
            continue
        kept.append(line)
    if not n:
        return False, "목록에서 찾지 못했습니다."
    _backup(p)
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return True, f"삭제했습니다: {word}"


def title_hits(conn, word):
    """이 단어가 들어 있는 수집 공고 제목 수 — 정상 검색어를 가리는 단어를 추가하기 전에 확인한다."""
    key = _squash(word)
    return sum(1 for (t,) in conn.execute("SELECT title FROM announcements") if key and key in _squash(t))


def matches(banned, term):
    """검색어가 걸리는 금칙어 목록(점검용). 예외 단어를 뺀 나머지로 비교한다."""
    banned._refresh()
    t = _squash(term)
    for a in banned.allow:
        t = t.replace(a, "")
    return [w for w in banned.words if w in t]


def recent_terms(conn, banned, days=30, limit=50, min_count=2, now=None):
    """관리자 점검용 최근 검색어 — 결과 0건 검색어와 금칙어 포함. 같은 검색어(소문자)끼리 묶는다.
    → [{term, count, hits(결과가 있었던 횟수), last, status('금칙어'|'표시 중'|'대기')}] 많은 순"""
    now = now or datetime.now()
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    agg = {}
    for r in conn.execute("SELECT term, norm, results, searched_at FROM search_logs WHERE searched_at >= ?", (since,)):
        a = agg.setdefault(r["norm"], {"forms": Counter(), "count": 0, "hits": 0, "last": ""})
        a["forms"][r["term"]] += 1
        a["count"] += 1
        a["hits"] += 1 if r["results"] > 0 else 0
        a["last"] = max(a["last"], r["searched_at"])
    rows = []
    for a in agg.values():
        term = a["forms"].most_common(1)[0][0]
        status = "금칙어" if banned.contains(term) else "표시 중" if a["hits"] >= min_count else "대기"
        rows.append({"term": term, "count": a["count"], "hits": a["hits"], "last": a["last"], "status": status})
    rows.sort(key=lambda r: (-r["count"], _neg(r["last"])))
    return rows[:limit]

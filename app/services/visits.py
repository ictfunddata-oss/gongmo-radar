"""수요자 화면 방문 수 집계(관리자 통계).

- 목록 화면과 공고 상세의 조회만 센다. 관리자가 로그인한 채 본 것, 검색엔진·점검 도구(봇)로 보이는 접속은 세지 않는다.
- 누구인지 알아볼 수 있는 값(IP·계정·브라우저 정보)은 저장하지 않는다. '순방문'은 (접속 주소 + 브라우저 정보)를 그날 하루만 쓰는 열쇠로
  섞어 만든 짧은 값의 개수이며, 다음 날에는 같은 사람이어도 다른 값이 되어 날짜를 넘어 따라갈 수 없다. 그 값은 60일 뒤 지운다.
- 순방문의 한계: 서버 앞에 프록시가 있으면 접속 주소가 같게 보여 실제보다 적게 센다. 같은 사람이 기기·브라우저를 바꾸면 따로 센다.
"""
import hashlib
import hmac
import re
from datetime import date, datetime, timedelta

BOT = re.compile(r"bot|crawl|spider|slurp|curl|wget|python-requests|httpclient|headless|monitor|preview|facebookexternalhit|lighthouse", re.I)
MOBILE = re.compile(r"mobi|android|iphone|ipad", re.I)
UNIQ_KEEP_DAYS = 60


def is_bot(ua):
    return not ua or bool(BOT.search(ua))


def device(ua):
    return "mobile" if MOBILE.search(ua or "") else "pc"


def visitor_hash(secret, day, ip, ua):
    """그날만 쓰는 열쇠로 만든 16자 값. 열쇠는 비밀키와 날짜를 섞어 매일 달라진다."""
    key = hashlib.sha256(f"{secret}|{day}".encode("utf-8")).digest()
    return hmac.new(key, f"{ip}|{ua}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def record(conn, kind, ann_id, ua, ip, secret, unique=True, now=None):
    """방문 1건을 센다. 센 경우 True, 봇이라 건너뛴 경우 False."""
    if is_bot(ua):
        return False
    now = now or datetime.now()
    day = now.date().isoformat()
    conn.execute("INSERT INTO visit_daily(day, kind, ann_id, device, views) VALUES (?,?,?,?,1) "
                 "ON CONFLICT(day, kind, ann_id, device) DO UPDATE SET views = views + 1",
                 (day, kind, int(ann_id or 0), device(ua)))
    if unique:
        conn.execute("INSERT INTO visit_uniq(day, vh) VALUES (?,?) ON CONFLICT(day, vh) DO NOTHING",
                     (day, visitor_hash(secret, day, ip, ua)))
        conn.execute("DELETE FROM visit_uniq WHERE day < ?", ((now.date() - timedelta(days=UNIQ_KEEP_DAYS)).isoformat(),))
    conn.commit()
    return True


def _days(n, now=None):
    end = (now or datetime.now()).date()
    return [(end - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def series(conn, n, now=None):
    """최근 n일의 일별 [{day, pv, list, detail, uniq}] — 방문이 없는 날도 0으로 채운다."""
    days = _days(n, now)
    pv = {r["day"]: (r["l"], r["d"]) for r in conn.execute(
        "SELECT day, SUM(CASE WHEN kind='list' THEN views ELSE 0 END) AS l, SUM(CASE WHEN kind='detail' THEN views ELSE 0 END) AS d "
        "FROM visit_daily WHERE day >= ? GROUP BY day", (days[0],))}
    uq = {r["day"]: r["n"] for r in conn.execute("SELECT day, COUNT(*) AS n FROM visit_uniq WHERE day >= ? GROUP BY day", (days[0],))}
    out = []
    for d in days:
        l, de = pv.get(d, (0, 0))
        out.append({"day": d, "list": l or 0, "detail": de or 0, "pv": (l or 0) + (de or 0), "uniq": uq.get(d, 0)})
    return out


def totals(rows):
    """series() 결과의 합계. 순방문은 '일별 순방문의 합'(여러 날에 온 같은 사람은 날마다 센다)이다."""
    return {"pv": sum(r["pv"] for r in rows), "list": sum(r["list"] for r in rows),
            "detail": sum(r["detail"] for r in rows), "uniq": sum(r["uniq"] for r in rows)}


def devices(conn, n, now=None):
    since = _days(n, now)[0]
    got = {r["device"]: r["v"] for r in conn.execute("SELECT device, SUM(views) AS v FROM visit_daily WHERE day >= ? GROUP BY device", (since,))}
    return {"pc": got.get("pc", 0), "mobile": got.get("mobile", 0)}


def top_notices(conn, n, limit=10, now=None):
    """최근 n일 동안 상세가 많이 열린 공고 → [{ann_id, title, org, views}]"""
    since = _days(n, now)[0]
    return [dict(r) for r in conn.execute(
        "SELECT v.ann_id, a.title, o.name AS org, SUM(v.views) AS views FROM visit_daily v "
        "JOIN announcements a ON a.ann_id = v.ann_id JOIN boards b ON b.board_id = a.board_id JOIN orgs o ON o.org_id = b.org_id "
        "WHERE v.kind='detail' AND v.day >= ? GROUP BY v.ann_id, a.title, o.name ORDER BY views DESC, v.ann_id DESC LIMIT ?", (since, limit))]

"""robots.txt 확인 — 수집을 시작하기 전에 사이트의 robots.txt 가 우리 경로를 막는지 본다(설계 F-CRW-08).

RFC 9309 의 처리 원칙을 따른다.
- 2xx: 규칙을 읽어 적용한다(우리는 '*' 규칙, 특정 로봇 이름만 지정한 규칙은 해당하지 않는다).
- 4xx(파일 없음 포함): 제한 없음으로 본다. RAPA처럼 없는 경로에 HTML 오류 쪽을 200으로 돌려주는 사이트도 규칙이 없는 것으로 읽힌다.
- 5xx·접속 실패: 확인할 수 없으니 이번 실행은 수집하지 않는다(조용히 넘어가지 않고 로그에 남긴다).
"""
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

AGENT = "*"


class RobotsGuard:
    def __init__(self, http, log, enabled=True):
        self.http = http
        self.log = log
        self.enabled = enabled
        self._rules = {}      # 출처(https://호스트) → RobotFileParser 또는 "deny"(확인 불가)

    def _load(self, origin):
        if origin in self._rules:
            return self._rules[origin]
        rp = RobotFileParser()
        try:
            r = self.http.s.get(origin + "/robots.txt", timeout=self.http.timeout)
        except Exception as e:      # 접속 실패 — 확인할 수 없다
            self.log.emit("WARN", f"robots.txt 확인 불가({type(e).__name__}) · {origin}")
            self._rules[origin] = "deny"
            return "deny"
        if r.status_code >= 500:
            self.log.emit("WARN", f"robots.txt 확인 불가(HTTP {r.status_code}) · {origin}")
            self._rules[origin] = "deny"
            return "deny"
        if r.status_code >= 400:
            rp.allow_all = True
        else:
            rp.parse(r.text.splitlines())
        self._rules[origin] = rp
        return rp

    def allowed(self, url):
        """이 주소를 수집해도 되는가. 확인 기능을 끄면(ROBOTS_CHECK=0) 항상 True."""
        if not self.enabled:
            return True
        parts = urlsplit(url)
        rp = self._load(f"{parts.scheme}://{parts.netloc}")
        return rp != "deny" and rp.can_fetch(AGENT, url)

"""공통 HTTP — 세션 유지, 브라우저 UA, 재시도, 실행 로그."""
import time
from datetime import datetime

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


class RunLog:
    def __init__(self, echo=True):
        self.lines = []
        self.echo = echo

    def emit(self, level, msg):
        line = {"ts": datetime.now().strftime("%H:%M:%S"), "lvl": level, "msg": msg}
        self.lines.append(line)
        if self.echo:
            print(f"{line['ts']} [{level:5}] {msg}", flush=True)


class HttpClient:
    def __init__(self, log, delay=0.3, timeout=20, retries=3):
        self.log = log
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def request(self, method, url, **kw):
        kw.setdefault("timeout", self.timeout)
        for attempt in range(1, self.retries + 1):
            t0 = time.time()
            try:
                r = self.s.request(method, url, **kw)
                r.raise_for_status()
                if time.time() - t0 > 2.5:
                    self.log.emit("WARN", f"응답 지연 {time.time() - t0:.1f}초 · {url}")
                return r
            except requests.RequestException as e:
                self.log.emit("WARN", f"접속 오류({type(e).__name__}) · {url} · 재시도 {attempt}/{self.retries}")
                time.sleep(2 * attempt)
        raise RuntimeError(f"요청 실패: {url}")

    def pause(self):
        time.sleep(self.delay)

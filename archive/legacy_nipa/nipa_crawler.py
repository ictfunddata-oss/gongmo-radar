"""NIPA 사업공고 수집기 (https://www.nipa.kr/home/2-2)

목록(?curPage=N) → 상세(/home/2-2/{id}) → SQLite 저장 → 엑셀 내보내기.

    python nipa_crawler.py --full          # 전체 페이지 수집
    python nipa_crawler.py                 # 증분: 새 글이 없는 페이지를 만나면 중단
    python nipa_crawler.py --pages 3       # 앞 3페이지만
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import openpyxl
import requests
from bs4 import BeautifulSoup

BASE = "https://www.nipa.kr"
LIST_URL = f"{BASE}/home/2-2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "data" / "nipa.db"
XLSX_PATH = HERE / "data" / "nipa_announcements.xlsx"

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY,          -- 게시물 ID (/home/2-2/{id})
    list_no INTEGER,                 -- 목록 번호
    title TEXT, biz TEXT,            -- 제목, 사업구분
    period_raw TEXT, start_at TEXT, end_at TEXT,
    site_status TEXT,                -- 목록에 표시된 상태(D-n/종료 등)
    writer TEXT, list_date TEXT, posted_at TEXT,  -- 목록 날짜 / 상세 작성일
    views INTEGER, body TEXT, body_len INTEGER,
    attach_count INTEGER, attach_bytes INTEGER,
    url TEXT, first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS attachments (
    ann_id INTEGER, seq INTEGER, name TEXT, ext TEXT,
    size_text TEXT, size_bytes INTEGER, url TEXT,
    PRIMARY KEY (ann_id, seq)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, mode TEXT, started_at TEXT, ended_at TEXT,
    pages_total INTEGER, pages_done INTEGER, rows INTEGER,
    new_rows INTEGER, updated_rows INTEGER, errors INTEGER, log TEXT
);
"""


def sp(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_period(raw):
    """'2026-10-01 09:00 ~ 2026-10-30 13:00' → (start, end) ISO 문자열. 날짜만 있으면 시각 생략."""
    found = re.findall(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?", raw or "")
    iso = [f"{d}T{t}" if t else d for d, t in found]
    return (iso[0] if iso else None, iso[1] if len(iso) > 1 else None)


def size_to_bytes(text):
    m = re.search(r"([\d.,]+)\s*(B|KB|MB|GB)", text or "", re.I)
    if not m:
        return 0
    mult = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[m.group(2).upper()]
    return int(float(m.group(1).replace(",", "")) * mult)


class Crawler:
    def __init__(self, delay):
        self.delay = delay
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        self.log = []

    def emit(self, level, msg):
        line = {"ts": datetime.now().strftime("%H:%M:%S"), "lvl": level, "msg": msg}
        self.log.append(line)
        print(f"{line['ts']} [{level:5}] {msg}", flush=True)

    def get(self, url, **kw):
        for attempt in range(1, 4):
            t0 = time.time()
            try:
                r = self.s.get(url, timeout=20, **kw)
                r.raise_for_status()
                if time.time() - t0 > 2.5:
                    self.emit("WARN", f"slow response {time.time() - t0:.1f}s · {url.replace(BASE, '')}")
                return r
            except requests.RequestException as e:
                self.emit("WARN", f"{type(e).__name__} · {url.replace(BASE, '')} · retry {attempt}/3")
                time.sleep(2 * attempt)
        raise RuntimeError(f"요청 실패: {url}")

    def list_page(self, page):
        soup = BeautifulSoup(self.get(LIST_URL, params={"curPage": page}).text, "lxml")
        # 마지막 묶음(예: 31~36)에서는 '마지막 페이지' 링크가 사라지므로 페이지 링크 중 최댓값을 쓴다
        nums = [int(n) for a in soup.select("ul.pagination a[href]")
                for n in re.findall(r"curPage=(\d+)", a["href"])]
        last_page = max(nums + [page])
        rows = []
        for tr in soup.select("table.tbgg tbody tr"):
            a = tr.select_one('a[href^="/home/2-2/"]')
            if not a:
                continue
            td = tr.find_all("td")
            period = re.search(r"신청기간\s*:\s*(.*)", sp(td[2].get_text(" ")))
            box = tr.select_one(".bluebox")
            rows.append({
                "id": int(a["href"].rsplit("/", 1)[1]),
                "list_no": int(sp(td[0].text)) if sp(td[0].text).isdigit() else None,
                "site_status": sp(td[1].text),
                "title": sp(a.get_text()),
                "biz": sp(box.text) if box else "",
                "period_raw": period.group(1) if period else "",
                "writer": sp(td[3].text),
                "list_date": sp(td[4].text),
            })
        return rows, last_page

    def detail(self, ann_id):
        soup = BeautifulSoup(self.get(f"{LIST_URL}/{ann_id}").text, "lxml")
        info = soup.select_one("td.ggtbInfo")
        d = {}
        if info:
            biz = info.select_one(".gdi1 .bluebox")
            per = info.select_one(".gdi2")
            d["biz"] = sp(biz.text) if biz else None
            d["period_raw"] = sp(per.text).replace("신청기간 :", "").strip() if per else None
            d["writer"] = sp(info.select_one(".infoNm").text) if info.select_one(".infoNm") else None
            d["posted_at"] = sp(info.select_one(".infoDt").text) if info.select_one(".infoDt") else None
            vw = info.select_one(".infoVw")
            d["views"] = int(re.sub(r"\D", "", vw.get_text()) or 0) if vw else None
        body = ""
        files = []
        for tr in soup.select("table.tb05 > tbody > tr, table.tb05 > tr"):
            head = tr.find("td", class_="bg_lightgray")
            if not head:
                continue
            label = sp(head.text)
            cell = head.find_next_sibling("td")
            if label == "내용" and cell:
                body = sp(cell.get_text(" "))
            elif label == "첨부파일" and cell:
                for i, a in enumerate(cell.select('a[href^="/comm/getFile"]'), 1):
                    text = sp(a.get_text(" "))
                    m = re.match(r"(.*?)\s*\(파일크기:\s*([^)]*?)\s*\)?$", text)
                    name = m.group(1) if m else text
                    size_text = m.group(2) if m else ""
                    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                    files.append({"seq": i, "name": name, "ext": ext, "size_text": size_text,
                                  "size_bytes": size_to_bytes(size_text), "url": BASE + a["href"]})
        d["body"] = body
        d["files"] = files
        return d


def save(conn, row, det, now):
    data = {**row, **{k: v for k, v in det.items() if v not in (None, "") and k != "files"}}
    data["start_at"], data["end_at"] = parse_period(data.get("period_raw"))
    data["body_len"] = len(data.get("body") or "")
    data["attach_count"] = len(det["files"])
    data["attach_bytes"] = sum(f["size_bytes"] for f in det["files"])
    data["url"] = f"{LIST_URL}/{row['id']}"
    exists = conn.execute("SELECT 1 FROM announcements WHERE id=?", (row["id"],)).fetchone()
    cols = ["id", "list_no", "title", "biz", "period_raw", "start_at", "end_at", "site_status",
            "writer", "list_date", "posted_at", "views", "body", "body_len",
            "attach_count", "attach_bytes", "url"]
    if exists:
        conn.execute(f"UPDATE announcements SET {', '.join(c + '=?' for c in cols[1:])}, last_seen=? WHERE id=?",
                     [data.get(c) for c in cols[1:]] + [now, row["id"]])
    else:
        conn.execute(f"INSERT INTO announcements ({', '.join(cols)}, first_seen, last_seen) "
                     f"VALUES ({', '.join('?' * (len(cols) + 2))})",
                     [data.get(c) for c in cols] + [now, now])
    conn.execute("DELETE FROM attachments WHERE ann_id=?", (row["id"],))
    conn.executemany("INSERT INTO attachments VALUES (?,?,?,?,?,?,?)",
                     [(row["id"], f["seq"], f["name"], f["ext"], f["size_text"], f["size_bytes"], f["url"])
                      for f in det["files"]])
    return not exists


def export_xlsx(conn):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NIPA 사업공고"
    head = ["게시물ID", "제목", "사업구분", "신청시작", "신청마감", "사이트상태", "작성자",
            "작성일", "조회수", "첨부수", "첨부용량(KB)", "URL", "최초수집", "최종수집"]
    ws.append(head)
    for r in conn.execute("SELECT id,title,biz,start_at,end_at,site_status,writer,posted_at,views,"
                          "attach_count,attach_bytes/1024,url,first_seen,last_seen "
                          "FROM announcements ORDER BY id DESC"):
        ws.append(list(r))
    ws2 = wb.create_sheet("첨부파일")
    ws2.append(["게시물ID", "순번", "파일명", "확장자", "크기", "다운로드URL"])
    for r in conn.execute("SELECT ann_id,seq,name,ext,size_text,url FROM attachments ORDER BY ann_id DESC, seq"):
        ws2.append(list(r))
    for sheet, widths in ((ws, [10, 60, 30, 17, 17, 10, 10, 12, 8, 7, 11, 36, 20, 20]),
                          (ws2, [10, 6, 70, 7, 10, 60])):
        for i, w in enumerate(widths):
            sheet.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w
    XLSX_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(XLSX_PATH)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="전체 페이지 수집")
    ap.add_argument("--pages", type=int, help="앞에서부터 N페이지만 수집")
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    known = {r[0] for r in conn.execute("SELECT id FROM announcements")}
    mode = "full" if args.full else (f"pages:{args.pages}" if args.pages else "incremental")
    started = datetime.now()
    run_id = started.strftime("CR-%Y-%m%d-%H%M")
    c = Crawler(args.delay)
    c.emit("INFO", f"run {run_id} start · mode={mode} · known={len(known)}")

    page, last_page, done, rows_n, new_n, upd_n, err_n = 1, 1, 0, 0, 0, 0, 0
    while True:
        t0 = time.time()
        try:
            rows, last_page = c.list_page(page)
        except RuntimeError as e:
            c.emit("ERR", str(e))
            err_n += 1
            break
        limit = args.pages or last_page
        new_on_page = 0
        for row in rows:
            try:
                det = c.detail(row["id"])
                is_new = save(conn, row, det, datetime.now().isoformat(timespec="seconds"))
                new_on_page += is_new
                new_n += is_new
                upd_n += not is_new
                rows_n += 1
                if is_new:
                    c.emit("FETCH", f"/home/2-2/{row['id']} · {row['title'][:40]}")
            except Exception as e:  # 한 건 실패로 전체 중단하지 않음
                err_n += 1
                c.emit("ERR", f"/home/2-2/{row['id']} · {type(e).__name__}: {e}")
            time.sleep(args.delay)
        conn.commit()
        done = page
        c.emit("OK", f"page {page}/{limit} — {len(rows)} rows · new {new_on_page} · {time.time() - t0:.1f}s")
        if page >= limit:
            break
        if mode == "incremental" and known and new_on_page == 0:
            c.emit("INFO", f"page {page}에 새 글 없음 → 증분 수집 종료")
            break
        page += 1

    export_xlsx(conn)
    ended = datetime.now()
    c.emit("INFO", f"done · rows {rows_n} · new {new_n} · errors {err_n} · {(ended - started).seconds}s")
    conn.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (run_id, mode, started.isoformat(timespec="seconds"), ended.isoformat(timespec="seconds"),
                  args.pages or last_page, done, rows_n, new_n, upd_n, err_n,
                  json.dumps(c.log[-200:], ensure_ascii=False)))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()

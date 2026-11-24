-- 공모사업 수집 DB (SQLite)
-- 설계 근거: docs/설계(안)/docs/20_데이터설계.md

CREATE TABLE IF NOT EXISTS orgs (
    org_id   INTEGER PRIMARY KEY,
    code     TEXT UNIQUE NOT NULL,          -- 예: nipa
    name     TEXT NOT NULL,                 -- 예: 정보통신산업진흥원
    kind     TEXT                           -- 전담기관 / 유관기관
);

CREATE TABLE IF NOT EXISTS boards (
    board_id INTEGER PRIMARY KEY,
    org_id   INTEGER NOT NULL REFERENCES orgs(org_id),
    code     TEXT UNIQUE NOT NULL,          -- 어댑터 코드, 예: nipa_business
    name     TEXT,                          -- 예: 사업공고
    list_url TEXT,
    enabled  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS announcements (
    ann_id       INTEGER PRIMARY KEY,
    board_id     INTEGER NOT NULL REFERENCES boards(board_id),
    post_no      TEXT NOT NULL,             -- 기관 사이트의 게시물 번호
    list_no      INTEGER,                   -- 목록 번호
    title        TEXT,
    biz          TEXT,                      -- 사업구분(내역사업명 역할)
    period_raw   TEXT,                      -- 사이트 신청기간 원문
    start_at     TEXT,
    end_at       TEXT,
    site_status  TEXT,
    writer       TEXT,                      -- 내부용. 외부 제공 데이터에서 제외
    list_date    TEXT,
    posted_at    TEXT,
    views        INTEGER,
    body         TEXT,
    body_len     INTEGER,
    attach_count INTEGER NOT NULL DEFAULT 0,
    attach_bytes INTEGER NOT NULL DEFAULT 0,
    url          TEXT,
    first_seen   TEXT,
    last_seen    TEXT,
    UNIQUE (board_id, post_no)
);
CREATE INDEX IF NOT EXISTS ix_ann_posted ON announcements(posted_at);
CREATE INDEX IF NOT EXISTS ix_ann_end ON announcements(end_at);

CREATE TABLE IF NOT EXISTS attachments (
    ann_id         INTEGER NOT NULL REFERENCES announcements(ann_id) ON DELETE CASCADE,
    seq            INTEGER NOT NULL,
    name           TEXT,                    -- 사이트에 표시된 파일명
    ext            TEXT,
    size_text      TEXT,
    size_bytes     INTEGER,
    url            TEXT,                    -- 다운로드 URL(토큰이 접속마다 바뀌어 만료됨)
    file_path      TEXT,                    -- ATTACHMENT_DIR 기준 상대경로
    file_size      INTEGER,
    sha256         TEXT,
    downloaded_at  TEXT,
    download_error TEXT,
    text_body      TEXT,                    -- 첨부에서 뽑은 글자. 이미지·스캔본은 비어 있음
    text_status    TEXT,                    -- ok / empty / encrypted / unsupported / error:...
    text_at        TEXT,
    PRIMARY KEY (ann_id, seq)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    board_id     INTEGER REFERENCES boards(board_id),
    mode         TEXT,
    started_at   TEXT,
    ended_at     TEXT,
    pages_total  INTEGER,
    pages_done   INTEGER,
    rows         INTEGER,
    new_rows     INTEGER,
    updated_rows INTEGER,
    files_saved  INTEGER NOT NULL DEFAULT 0,
    errors       INTEGER,
    status       TEXT,                      -- 정상 / 주의 / 오류
    log          TEXT                       -- JSON 배열
);

-- 수요자 화면 검색어 기록(F-SVC-18). 검색한 사람은 저장하지 않는다.
CREATE TABLE IF NOT EXISTS search_logs (
    log_id      INTEGER PRIMARY KEY,
    term        TEXT NOT NULL,          -- 입력한 표기(공백 정리)
    norm        TEXT NOT NULL,          -- 소문자로 맞춘 값(같은 검색어 묶기용)
    results     INTEGER NOT NULL,       -- 그때 화면에 나온 결과 건수
    searched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_search_at ON search_logs(searched_at);

-- 자동화(ADR-038): 설정·예약 상태(키-값), 실행 기록, 중복 실행 방지용 잠금
CREATE TABLE IF NOT EXISTS app_kv (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
CREATE TABLE IF NOT EXISTS automation_runs (
    run_id      INTEGER PRIMARY KEY,
    trigger     TEXT,                   -- 예약 / 수동(지금 실행) / 명령
    started_at  TEXT,
    ended_at    TEXT,
    status      TEXT,                   -- 실행 중 / 정상 / 주의 / 오류
    summary     TEXT,                   -- JSON: 단계별 결과
    log         TEXT                    -- JSON 배열
);
CREATE TABLE IF NOT EXISTS automation_lock (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    owner      TEXT,
    heartbeat  TEXT
);

-- 관리자 통계·로그(2026-11): 방문 수·운영 이력.
-- 방문 기록에는 IP·계정·브라우저 정보를 저장하지 않는다. 하루 단위로 바뀌는 열쇠로 만든 짧은 값(visit_uniq.vh)만 그날의 '순방문'을 세는 데 쓰고 60일 뒤 지운다.
CREATE TABLE IF NOT EXISTS visit_daily (
    day     TEXT NOT NULL,                  -- YYYY-MM-DD
    kind    TEXT NOT NULL,                  -- list(목록 화면) / detail(공고 상세)
    ann_id  INTEGER NOT NULL DEFAULT 0,     -- 상세일 때 공고 번호, 목록은 0
    device  TEXT NOT NULL DEFAULT '',       -- pc / mobile
    views   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind, ann_id, device)
);
CREATE TABLE IF NOT EXISTS visit_uniq (
    day  TEXT NOT NULL,
    vh   TEXT NOT NULL,
    PRIMARY KEY (day, vh)
);
-- 운영 이력: 관리자가 바꾼 것과 로그인 시도
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id  INTEGER PRIMARY KEY,
    at      TEXT NOT NULL,
    actor   TEXT,                           -- 관리자 아이디(로그인 실패는 '(알 수 없음)')
    action  TEXT NOT NULL,                  -- 예: 노출 변경, 규칙 저장, 로그인 실패
    target  TEXT,                           -- 대상(공고 번호·규칙 이름·단어 등)
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_at ON audit_logs(at);

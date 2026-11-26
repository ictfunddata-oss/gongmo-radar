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
    text_engine    TEXT,                    -- 글자를 읽은 방법: kordoc / legacy (ADR-050)
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

-- 공고 유형 분류(ADR-045·048). 공고당 한 줄. source='manual'은 API·가져오기가 덮어쓰지 않는다
CREATE TABLE IF NOT EXISTS announcement_labels (
    ann_id         INTEGER PRIMARY KEY REFERENCES announcements(ann_id) ON DELETE CASCADE,
    class          TEXT,                  -- 공모지원사업 / 입찰공고 / 기타. 분류 보류면 NULL
    sub            TEXT,                  -- 5.6 표. 수동 확인이면 NULL일 수 있음
    confidence     TEXT,                  -- high / mid / low
    reason         TEXT,
    status         TEXT NOT NULL,         -- 확정 / 수동 확인 / 분류 보류
    source         TEXT NOT NULL,         -- api / manual
    prompt_version TEXT,                  -- classify_v2
    model          TEXT,                  -- 실제 응답 모델(대체되면 대체 모델)
    request_id     TEXT,                  -- API 요청 ID, 일괄 처리는 'batch:<id>', CLI 가져오기는 'cli:<실행 이름>'
    input_hash     TEXT,
    labeled_at     TEXT NOT NULL,
    labeled_by     TEXT                   -- manual일 때 관리자 아이디
);
CREATE INDEX IF NOT EXISTS ix_label_class ON announcement_labels(class);

-- 상세화면 표준 필드(ADR-045·051). 공고 × 칸 한 줄. 원래 칸(period_raw·start_at·end_at·body)은 덮어쓰지 않는다
CREATE TABLE IF NOT EXISTS announcement_fields (
    ann_id         INTEGER NOT NULL REFERENCES announcements(ann_id) ON DELETE CASCADE,
    field          TEXT NOT NULL,         -- title / content / qualify / area / period
    value          TEXT,                  -- 원문 발췌(평문, 1,500자 이내). 미확인·해당 없음이면 NULL
    start_at       TEXT,                  -- period만. announcements.start_at과 같은 형식
    end_at         TEXT,
    source         TEXT,                  -- site / body / attachment
    source_ref     TEXT,                  -- 첨부 파일명(zip이면 'zip이름/안의 이름')
    evidence       TEXT,                  -- 근거가 된 원문 한 줄(200자 이내, 운영 화면용)
    status         TEXT NOT NULL,         -- 확인 / 미확인 / 해당 없음 / 충돌
    note           TEXT,                  -- 충돌일 때 다른 출처의 값, 인용 불일치 등
    method         TEXT NOT NULL,         -- rule / api
    prompt_version TEXT,                  -- method=api일 때 extract_v1
    input_hash     TEXT NOT NULL,
    extracted_at   TEXT NOT NULL,
    PRIMARY KEY (ann_id, field)
);

-- Claude API 호출 기록(비용 실측, I-11)
CREATE TABLE IF NOT EXISTS llm_calls (
    call_id            INTEGER PRIMARY KEY,
    run_id             INTEGER,           -- automation_runs.run_id, 명령으로 돌리면 NULL
    stage              TEXT NOT NULL,     -- classify / extract
    mode               TEXT NOT NULL,     -- sync / batch
    model              TEXT,              -- 요청한 모델
    served_model       TEXT,              -- 응답한 모델
    fallback           INTEGER NOT NULL DEFAULT 0,
    request_id         TEXT,
    items              INTEGER,           -- 이 호출에 담은 공고 수
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    cache_read_tokens  INTEGER,
    cache_write_tokens INTEGER,
    cost_usd           REAL,              -- 단가표로 계산한 추정값. 단가를 모르는 모델이면 NULL
    outcome            TEXT NOT NULL,     -- ok / refusal / max_tokens / invalid / error
    error              TEXT,
    started_at         TEXT NOT NULL,
    ms                 INTEGER
);
CREATE INDEX IF NOT EXISTS ix_llm_at ON llm_calls(started_at);

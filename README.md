# 공모사업 수집 웹앱

ICT기금 「사용자 중심 AX서비스 구축 계획」의 **공모사업 파이프라인** 구현체다. 전담·유관기관 게시판의 공고와 첨부파일을 수집해 SQLite에 쌓고, 수집한 그대로 웹 화면과 API로 보여 준다. 운영 화면에서 방문·검색어 통계와 수집·운영 로그를 본다.

> 공고를 AI로 판별·분류해 노출 여부를 정하던 기능(분류 체계, 선별 규칙, AI 판별, 노출 규칙)은 2026-11-20에 모두 삭제했다(ADR-044). 삭제 전 코드·DB·문서는 `data/bak_remove_cls_1120/`에 있다.

- 스택: Python 3.12 · Flask 3 · SQLite · requests/BeautifulSoup · pypdf/olefile(첨부 글자 추출)
- 수집 대상: 정보통신산업진흥원(NIPA)·한국지능정보사회진흥원(NIA)·한국전파진흥협회(RAPA)·한국방송통신전파진흥원(KCA) 게시판. 기관은 어댑터를 추가해 넓힌다.
- 설계 문서: `docs/설계(안)/index.html` (기능정의서·데이터 설계·결정 기록)

## 폴더 구조

```
공모사업 웹크롤링/
├── run.py                  # 개발 서버 진입점, flask --app run <명령>
├── requirements.txt
├── .env.example            # 설정 예시 → .env 로 복사해 사용
├── app/
│   ├── __init__.py         # create_app()
│   ├── config.py           # .env 로딩(경로·수집·화면 설정)
│   ├── db.py, schema.sql   # SQLite 연결·스키마
│   ├── cli.py              # 관리 명령(crawl, attach-text, export …)
│   ├── crawler/            # 수집(어댑터, http, robots.txt 확인, 첨부 다운로드, runner)
│   ├── automation/         # 예약 수집(설정·스케줄러·파이프라인)
│   ├── services/           # 화면용 조회(public, announcements), 통계(visits, admin_stats, audit),
│   │                       #   검색어, 첨부 글자 추출(extract, attach_text), 엑셀·JSON 내보내기
│   ├── web/                # public(수요자 화면) · admin(운영 화면) · api 블루프린트
│   ├── templates/          # public/ · admin/
│   └── static/             # public.css·public.js, admin.css
├── tests/                  # 파싱·통계·첨부 추출 단위 테스트(HTML 스냅샷 사용)
├── data/                   # 실행 데이터(.gitignore) — gongmo.db, attachments/, exports/, 백업
├── design/                 # 화면 시안(HTML)
├── docs/
│   ├── 설계(안)/           # 설계 문서 허브(md 원본 + index.html)
│   ├── UI_디자인(안)/      # 대시보드 UI 시안
│   └── 기획/               # AX계획·추진계획(hwpx), 점검 결과·성과지표(xlsx)
└── archive/                # 정리 전 자료 보관(삭제하지 않음)
```

## 설치

```bash
pip install -r requirements.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env
```

## 설정 (.env)

| 키 | 기본값 | 설명 |
|---|---|---|
| `DATA_DIR` | `./data` | 실행 데이터 기본 폴더 |
| `DB_PATH` | `{DATA_DIR}/gongmo.db` | SQLite 파일 |
| `ATTACHMENT_DIR` | `{DATA_DIR}/attachments` | 첨부 저장 경로 |
| `EXPORT_DIR` | `{DATA_DIR}/exports` | 엑셀·JSON 내보내기 위치 |
| `CRAWL_DELAY` | `0.3` | 요청 간격(초). 0.3 미만으로 낮추지 않는다 |
| `ROBOTS_CHECK` | `1` | 수집 전 robots.txt 확인(확인할 수 없거나 막혀 있으면 그 실행은 수집하지 않음) |
| `DOWNLOAD_ATTACHMENTS` | `1` | 신규 공고 첨부를 수집 시점에 저장 |
| `ATTACH_MAX_MB` | `200` | 첨부 1개 용량 상한 |
| `ATTACH_TEXT_MIN_BODY` · `ATTACH_TEXT_FILES` | `200` · `3` | 첨부 글자 추출 대상(본문이 이보다 짧은 공고)과 공고당 읽는 파일 수 |
| `PUBLIC_SHOW_ENDED` | `1` | 접수 마감 공고를 기본 필터에 포함할지(1/0). 운영 때는 0 권장 |
| `VISIT_LOG` · `VISIT_UNIQUE` | `1` · `1` | 수요자 화면 방문 수 집계, 하루 단위 순방문 집계 |
| `ADMIN_ID` | `admin` | 관리자 아이디 |
| `ADMIN_PASSWORD_HASH` | (없음) | 관리자 비밀번호 해시. 직접 적지 말고 `flask --app run set-admin-password`로 설정. 없으면 운영 화면이 열리지 않는다 |
| `ADMIN_SESSION_HOURS` · `ADMIN_COOKIE_SECURE` | `8` · `0` | 로그인 유지 시간, https 배포 시 1 |
| `AUTOMATION_SCHEDULER` | `1` | 웹 서버가 예약 실행기를 함께 띄울지. 별도 `automation-daemon`으로 돌릴 때는 `0` |

경로는 절대경로 또는 프로젝트 루트 기준 상대경로를 쓴다.

## 사용법

모든 관리 명령은 프로젝트 루트에서 `flask --app run <명령>`으로 실행한다.

| 명령 | 하는 일 |
|---|---|
| `init-db` | 스키마 생성(이미 있으면 그대로) |
| `boards` | 등록된 게시판 어댑터 목록 |
| `crawl [--board 코드] [--full] [--pages N] [--no-attachments]` | 공고 수집. 기본은 새 글이 없는 쪽에서 멈추는 증분 수집이며, 신규 공고의 첨부는 그 자리에서 저장 |
| `fetch-attachments [--board 코드] [--since YYYY-MM-DD] [--limit N]` | 이미 수집한 공고 중 첨부를 아직 받지 않은 것을 받음(상세 페이지를 다시 읽어 새 링크로 다운로드) |
| `attach-text [--limit N] [--since 날짜] [--ann-id ID] [--redo] [--no-download] [--dry-run]` | 본문이 짧은 공고의 첨부(HWP·HWPX·PDF·DOCX)에서 글자를 뽑아 DB에 저장. 외부 서비스는 쓰지 않는다 |
| `automation-run [--force]` | 저장된 자동화 설정대로 수집을 한 번 실행(cron·Windows 작업 스케줄러용) |
| `automation-daemon` | 예약 실행기만 따로 실행(웹은 `AUTOMATION_SCHEDULER=0`) |
| `migrate-legacy [--source 경로]` | 구 NIPA DB를 새 스키마로 이관하고 건수 대조(빈 DB에서 1회) |
| `export` · `export-json` | 공고·첨부 목록 엑셀, 공고별 원본 JSON 저장 |
| `set-admin-password` | 관리자 비밀번호 설정 |

```bash
flask --app run crawl                      # 새 공고 수집 + 첨부 저장
flask --app run attach-text --limit 100    # 본문이 짧은 공고의 첨부 글자 추출
python run.py                              # http://127.0.0.1:5000 (수요자 화면), /admin (운영 화면)
```

> 첨부 다운로드 링크의 토큰은 접속할 때마다 바뀌어 저장된 URL은 금방 만료된다. 그래서 첨부는 상세 페이지를 읽은 같은 세션에서 바로 받고, 나중에 받을 때는 `fetch-attachments`·`attach-text`가 상세 페이지를 다시 읽는다.

## 데이터

| 테이블 | 내용 |
|---|---|
| `orgs`, `boards` | 기관·게시판(어댑터 실행 시 자동 등록) |
| `announcements` | 공고. 키는 `(board_id, post_no)` — 기관마다 게시물 번호가 겹치기 때문 |
| `attachments` | 첨부 목록 + 저장 정보(`file_path`는 `ATTACHMENT_DIR` 기준 상대경로, `sha256`, `download_error`) + 추출한 글자(`text_body`, `text_status`) |
| `runs` | 수집 실행 기록(처리·신규·갱신·첨부·오류 건수, 상태, 로그) |
| `search_logs` | 수요자 화면 검색어 기록(검색한 사람은 저장하지 않음) |
| `visit_daily`, `visit_uniq` | 방문 수 집계. IP·계정·브라우저 정보는 저장하지 않고, 순방문 값은 하루 단위로 바뀌며 60일 뒤 삭제 |
| `audit_logs` | 운영 이력(관리자 변경·로그인 시도, 1년 보관) |
| `app_kv`, `automation_runs`, `automation_lock` | 자동화 설정·실행 기록·중복 실행 방지 |

첨부 파일은 `{ATTACHMENT_DIR}/{게시판코드}/{게시물번호}/{순번}_{원래 파일명}`으로 저장한다.

## 웹 화면·API

| 경로 | 내용 |
|---|---|
| `/` | **수요자 화면** — 수집한 공고 전체. 검색, 접수 상태·기관 필터, 카드 목록, D-day, 곧 마감 띠, 관심 공고 |
| `/notice/<id>` | 공고 상세 — 수집한 정보, 본문, 첨부 내려받기, (있으면) 첨부에서 읽어 정리한 내용 |
| `/admin/login` | 관리자 로그인(아래 `/admin/` 이하와 운영용 API는 로그인 필요) |
| `/admin/dashboard` | **통계** — 방문·순방문, 검색 현황, 많이 본 공고, 검색어, 기관별 수집 현황, 최근 문제 알림 |
| `/admin/` | 전체 공고 목록 · `/admin/announcements/<id>` 상세 |
| `/admin/raw` | 원본 데이터 — 수집한 공고 전체와 첨부 구조화 현황 |
| `/admin/searches` | 검색어 통계(기간별, 결과 없음 검색어, CSV) |
| `/admin/banned` | 금칙어 관리 — '많이 찾는 검색어'에서 뺄 단어 |
| `/admin/automation` | 자동화 — 예약 시각·요일·대상 게시판 설정, 지금 실행, 실행 기록 |
| `/admin/logs` | 로그 — 수집 실행, 자동 실행, 운영 이력 |
| `/api/public/announcements` | 수요자 화면과 같은 공고 JSON |
| `/api/announcements?q=&limit=&offset=` | 공고 목록 JSON(운영용) |
| `/api/announcements/<id>` · `/api/stats` | 공고 상세·수집 현황 JSON(운영용) |

- **접수 상태**: 서버가 페이지 요청 시각 기준으로 계산한다. 제목에 '[접수마감]'이 있으면 마감, 기간 표기가 없고 게시 1년이 지났으면 마감.
- **개인정보**: 작성자(담당자 이름)는 넣지 않고, 본문의 이메일·전화번호는 가린다.

## 기관 추가

1. `app/crawler/adapters/{기관}.py`에 `BoardAdapter`를 상속한 클래스를 만든다(`list_page_url`, `detail_url`, `parse_list`, `parse_detail`).
2. `app/crawler/adapters/__init__.py`의 `ADAPTERS`에 등록한다.
3. 목록·상세 HTML을 `tests/fixtures/`에 저장하고 파싱 테스트를 추가한다.
4. `flask --app run crawl --board {코드} --pages 1`로 확인한다.

## 테스트

```bash
python -m unittest discover -s tests -q
```

## 남은 일

- 1단계 기관(KISA·KAIT·ETRI 등) 어댑터 추가
- 한국전파진흥협회 게시판의 빈 본문·신청기간 원인 확인
- 공고를 어떻게 정리·분류해 보여 줄지 다시 정하기(이전 판별 기능은 삭제됨)

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## 명령

```bash
pip install -r requirements.txt
cp .env.example .env

python -m unittest discover -s tests -q                        # 전체 테스트
python -m unittest tests.test_kca_adapter                      # 파일 하나
python -m unittest tests.test_kca_adapter.KcaTest.test_urls    # 테스트 하나

./run-app.sh                                   # 가상환경·.env 준비 후 개발 서버 http://127.0.0.1:5001 (PORT=로 변경)
python run.py                                  # 포트 5000 고정 — macOS에서는 제어 센터(AirPlay 수신)와 겹친다
flask --app run set-admin-password             # 이걸 먼저 해야 /admin·/api가 열린다(안 하면 503)
flask --app run crawl --board <코드> --pages 1  # 어댑터를 실제 사이트에 붙여 확인
```

- 관리 명령은 모두 `flask --app run <명령>` 형식이다. 전체 목록은 README의 「사용법」 표에 있다.
- 린터·타입 검사·빌드 설정은 없다. package.json도 없으므로 AGENTS.md에 적힌 `pnpm`·`npx tsc` 명령은 이 저장소에서 실행되지 않는다. 테스트는 위의 unittest다.
- 테스트는 네트워크를 쓰지 않는다. 파서는 `tests/fixtures/*.html` 스냅샷으로 검사하고, DB가 필요하면 임시 파일이나 `:memory:`에 `tests/helpers.SCHEMA`를 넣어 쓴다. `create_app(overrides)`에 overrides를 넘기면 예약 실행기가 뜨지 않는다.

## 구조

데이터 흐름: 기관 게시판 → `app/crawler` → SQLite(`data/gongmo.db`) + 첨부 파일(`data/attachments/`) → `app/services` → `app/web`(화면·JSON).

### 앱 시작
- `create_app()`(`app/__init__.py`)이 `.env`를 읽고(`config.py`, 상대경로는 프로젝트 루트 기준) 데이터 폴더를 만든 뒤, 시작할 때마다 `schema.sql`을 실행한다.
- `schema.sql`은 `CREATE TABLE IF NOT EXISTS`로만 되어 있어 기존 표에 열을 더하지 못한다. 기존 표에 열을 추가할 때는 `db._migrate()`에도 넣는다(`NEW_ATT_COLUMNS` 참고).
- ORM 없이 `sqlite3`(Row)를 직접 쓴다. 요청 안에서는 `db.get_db()`, CLI·스레드에서는 `db.connect()`를 쓴다.
- 예약 실행기 스레드는 웹 서버로 뜰 때만 시작한다(`automation/scheduler.should_autostart`).

### 수집 (`app/crawler`)
- 어댑터(`adapters/*.py`)는 URL과 HTML 파싱만 맡는다. 목록·상세 결과는 `base.py` docstring에 정한 표준 키의 dict로 돌려준다. 저장·첨부·재시도·robots 확인은 `runner.py`·`attachments.py`·`http.py`·`robots.py`가 공통으로 처리한다.
- 새 기관을 붙이려면 어댑터 파일을 만들고, `adapters/__init__.py`의 `ADAPTERS`에 등록하고, fixture HTML과 파싱 테스트를 추가한다. 게시판에 신청기간 칸이 없으면 `nia.extract_period()`로 본문에서 찾는다(RAPA·KCA가 이 방식).
- 공고 키는 `(board_id, post_no)`다. 기관마다 게시물 번호가 겹치기 때문이다.
- 첨부 다운로드 링크의 토큰은 접속할 때마다 바뀐다. 그래서 첨부는 상세 페이지를 읽은 그 세션에서 바로 받는다. 나중에 받을 때(`fetch_attachments`, `attach-text`)는 상세 페이지를 다시 읽는다.
- robots.txt를 확인할 수 없거나 경로가 막혀 있으면 그 실행은 수집하지 않는다. `CRAWL_DELAY`는 0.3초보다 낮추지 않는다.
- 증분 수집은 신규 공고가 0건인 쪽에서 멈춘다. 고정 공지만 있는 쪽은 이 판단에서 뺀다(`is_pinned`).

### 자동화 (`app/automation`)
- 설정은 `app_kv` 표에 JSON으로 저장한다(`settings.py`). `scheduler.tick()`이 15초마다 예약 시각을 보고 `pipeline.run_pipeline()`을 실행하며, 이 함수가 게시판마다 `crawl()`을 부른다.
- 실행하는 곳은 웹 안 스레드, `automation-daemon`, `automation-run`(cron용), 운영 화면의 '지금 실행' 네 가지다. 모두 같은 DB를 쓰므로 `automation_lock` 표의 박동(heartbeat)으로 한 번에 하나만 돌게 한다.

### 화면 (`app/web`, `app/services`)
- `public`은 로그인 없이 열린다. `admin`·`api` 블루프린트는 `auth.require_admin`이 `before_request`에서 막는다. 예외는 `auth.OPEN_ENDPOINTS`(공개 API)뿐이다.
- 수요자 목록은 서버가 공고 전체의 접수 상태를 계산해(`services/public.status`) 페이지 안 JSON으로 한 번에 보낸다. 검색·필터·정렬·쪽 나누기는 `static/public.js`가 브라우저에서 처리한다. 목록 필터를 바꾸려면 SQL이 아니라 이 JS를 고친다.
- 금칙어 목록은 `app/banned_terms.txt` 파일이다. 파일 수정 시각(mtime)이 바뀌면 다시 읽고, 운영 화면에서 고치면 이 파일을 직접 쓴다(쓰기 전 `.bak`로 백업).
- '첨부 구조화' 표시는 `DATA_DIR` 안의 이름이 정해진 JSON 파일 3개(`services/raw_view.STRUCT_FILES`)를 읽는다. 이 파일을 만드는 코드는 저장소에 없다.

### 데이터 규칙
- 작성자(`writer`)는 내부용이다. 화면·공개 API·요약에는 넣지 않는다. 본문은 `services/mask.mask_contacts()`로 이메일·전화번호를 가린 뒤 보여 준다.
- 방문·검색 기록에는 IP·계정·브라우저 정보를 저장하지 않는다(ADR-042). 순방문은 하루만 쓰는 HMAC 값으로 세고 60일 뒤 지운다.

## 문서와 결정 기록
- 설계 문서의 원본은 `docs/설계(안)/docs/*.md`다. `index.html`은 생성물이라 직접 고치지 않는다. md를 고치면 머리말의 `version`·`updated`를 올리고, `90_개정이력.md`에 한 줄 추가한 뒤, `docs/설계(안)/build_index.py`를 실행한다.
- 결정은 `40_결정기록.md`에 `ADR-NNN`으로, 미결 사항은 `I-NN`으로 남긴다. 행은 지우지 않고 상태만 바꾼다. 코드 docstring에 나오는 `F-SVC-20`·`ADR-038` 같은 ID가 이 문서들을 가리킨다.
- 공고 AI 판별·분류·선별·노출 기능은 2026-11-20에 모두 삭제됐다(ADR-044). 설계 문서의 FS-SEL·FS-CLS와 관련 ADR은 당시 기록일 뿐이고, 현재 코드의 명세가 아니다.
- `data/`, `.env`, `docs/기획/`(내부 기획 문서)은 저장소에 올리지 않는다.

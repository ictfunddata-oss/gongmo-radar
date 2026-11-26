# 작업 지시 — w-kordoc

첨부 글자 읽기에 kordoc CLI를 넣습니다(ADR-050).

## 할 일 (00 6장 3단계 「W-kordoc」, 5.4의 kordoc·extract·attach_text 행, 부록 C.7)
- `app/services/kordoc.py` — `to_text(path, cfg) -> (text or None, status)`. status: ok / empty / timeout / error:<사유>. `subprocess.run(shlex.split(cfg["KORDOC_CMD"]) + [str(path)], capture_output=True, timeout=cfg["KORDOC_TIMEOUT"], cwd=<임시 폴더>)`. 표준 출력(markdown)을 `extract.MAX_CHARS`에서 자르고, 종료 코드 ≠ 0·시간 초과·글자 수 `extract.MIN_USEFUL` 미만은 실패. `--ocr`은 넣지 않습니다. `cfg["KORDOC_ENABLED"]`가 꺼져 있으면 부르지 않습니다.
  - **Windows 주의**: `npx`는 `npx.cmd`라 `shutil.which`로 찾아야 하고, 시간 초과 때 자식 node가 남아 `communicate`가 멈춥니다. 시간 초과면 프로세스 트리를 끝내세요(Windows `taskkill /T /F /PID`, 그 밖 `os.killpg`). 참고 구현: `plan/validation/dump_gold_src.py`의 `kordoc()`·`_kill_tree()`.
- `app/services/extract.py` — 새 함수 `read_text(path, ext, cfg) -> (text, status, engine)`: kordoc을 먼저, 실패하면 기존 `extract_text`(engine='legacy'). **기존 `extract_text`의 시그니처와 동작은 바꾸지 않습니다.**
- `app/services/attach_text.py` — `targets(..., any_body=False)`(True면 본문 길이와 상관없이), `process()`가 `read_text` 사용, zip 처리(부록 C.7: 풀어서 안의 hwp·hwpx·pdf·docx, cp949 이름, `../` 경로 탈출 거부, 크기 상한), hwp/hwpx 우선(같은 이름의 hwp/hwpx가 있으면 pdf는 고르지 않음), `text_engine` 저장. `text_status` 값의 뜻(ok/empty/…)은 바꾸지 않습니다.
- 테스트(`subprocess.run`을 가짜로): 성공 / 0이 아닌 종료 / 시간 초과 / 빈 출력 → 기존 추출기로 넘어감, zip 안 cp949 이름, zip 경로 탈출 거부, 크기 상한, hwp·pdf 중복 제거, `any_body`. 기존 `tests/test_attach_text.py` 통과.
- 실제 확인(테스트 밖, 한 번): `.venv/Scripts/flask --app run attach-text --ann-id <id> --redo --no-download`로 KCA 6239644(hwp, ann_id 35), NIPA 17006(hwpx, ann_id 1), NIPA 16953(zip, ann_id 7)을 읽고 `text_engine='kordoc'`이고 표가 살아 있는지 `.venv/Scripts/python -c`로 DB를 읽어 보고서에 적습니다. 지금 CLI에는 `--any-body`가 없으므로(4단계에서 코디네이터가 추가) 본문이 긴 공고면 결과가 없을 수 있습니다. 그 경우 그대로 적습니다.

## 쓰기 허용
- `app/services/kordoc.py`
- `app/services/extract.py`
- `app/services/attach_text.py`
- `tests/test_kordoc.py`
- `tests/test_attach_text.py`
- `tests/fixtures/kordoc/**`
- `.team/out/w-kordoc/**`

## 공통 규칙
- 먼저 `AGENTS.md`·`CLAUDE.md`를 읽습니다. 이 저장소의 테스트는 unittest입니다(pnpm·tsc 없음). 이 PC는 Windows라 가상환경 경로가 `.venv/Scripts/python`입니다(문서의 `.venv/bin/python` 대신).
- 계약은 `plan/00_구현핸드오프.md` 「5장 공통 계약」이 기준입니다. 계약을 바꿔야 할 것 같으면 바꾸지 말고 보고서에 적습니다.
- 2단계 산출물(이미 있음, 읽기만): `app/schema.sql`(announcement_labels·announcement_fields·llm_calls, attachments.text_engine), `app/config.py`(CLAUDE_*·KORDOC_*), `app/services/labels.py`, `app/services/fields/model.py`·`__init__.py`, `app/automation/settings.py`(새 단계 키).
- 쓰기는 아래 「쓰기 허용」 경로만 합니다. 공용 파일(`app/schema.sql`, `app/db.py`, `app/config.py`, `app/cli.py`, `app/__init__.py`, `app/automation/**`, `app/crawler/**`, `app/services/labels.py`, `app/services/fields/__init__.py`·`model.py`, `requirements.txt`, 문서)은 고치지 않습니다. 필요하면 보고서에 적습니다.
- 「9. 하지 않을 것」을 지킵니다: 실제 Claude API·네트워크·kordoc을 부르는 테스트 금지, `.env` 수정·비밀값 기록 금지, 문서에 없는 기능·관계없는 정리 금지, 커밋 금지(코디네이터가 커밋), 인터넷 사용 금지.
- 테스트: `.venv/Scripts/python -m unittest discover -s tests -q` 전체가 통과해야 합니다(다른 워커가 동시에 작업 중이라 그쪽 테스트가 잠시 깨져 있으면 보고서에 적고 내 테스트만 확인).
- 질문이 생겨도 멈추지 말고 가장 타당한 판단을 한 뒤 보고서에 적습니다.
- 끝나면 `.team/out/w-kordoc/report.md`를 씁니다: 바꾼 파일과 이유, 테스트 명령과 결과 줄, 계약과 다르게 한 점, 알게 된 문제. **마지막 줄은 `STATUS: DONE`** 입니다.

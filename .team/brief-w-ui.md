# 작업 지시 — w-ui

화면을 만듭니다(F-SVC-29·30, ADR-047·051·052).

## 할 일 (00 6장 3단계 「W-ui」, 부록 D 전부)
- D.1 수요자 목록(`services/public.py`, `static/public.js`): 유형 필터·배지(기본: 공모지원사업 + 미분류), 목록 항목에 type.
- D.2 수요자 상세(`templates/public/detail.html`): '공고 표준 정보' 블록(다섯 칸, `fields.load`·`fields.model.LABELS`), 유형 배지. 자동 이스케이프(`|safe` 금지).
- D.3 운영 화면: '분류·정리' 화면(`services/admin_labels.py`), 운영 상세의 유형 수정(`labels.set_manual`, 로그인 필요, 잘못된 sub 거부), 자동화 화면의 단계 스위치(5.3 키, 저장은 기존 `settings.clean`).
- `app/web/public.py`는 1단계에서 `search_log`를 바꿨습니다(서버가 결과 수를 다시 셈). 그 부분은 유지합니다.
- 운영 화면의 원문 보기(`services/raw_view.STRUCT_FILES`)는 그대로 둡니다. 공개 API(`/api/public/announcements`)와 엑셀 내보내기에는 유형·표준 필드를 넣지 않습니다.
- 테스트: `public_item`이 type·sub·fields를 돌려줌, 목록 항목에 type, 유형 수정(로그인 필요, 운영 이력 기록, 잘못된 sub 거부), '분류·정리' 화면이 빈 DB와 채운 DB에서 200, 자동화 설정 저장에 새 키 반영. 기존 `tests/test_public_item.py` 등 통과.

## 쓰기 허용
- `app/services/public.py`
- `app/services/admin_labels.py`
- `app/static/**`
- `app/templates/**`
- `app/web/admin.py`
- `app/web/public.py`
- `tests/test_public_item.py`
- `tests/test_admin_labels.py`
- `.team/out/w-ui/**`

## 공통 규칙
- 먼저 `AGENTS.md`·`CLAUDE.md`를 읽습니다. 이 저장소의 테스트는 unittest입니다(pnpm·tsc 없음). 이 PC는 Windows라 가상환경 경로가 `.venv/Scripts/python`입니다(문서의 `.venv/bin/python` 대신).
- 계약은 `plan/00_구현핸드오프.md` 「5장 공통 계약」이 기준입니다. 계약을 바꿔야 할 것 같으면 바꾸지 말고 보고서에 적습니다.
- 2단계 산출물(이미 있음, 읽기만): `app/schema.sql`(announcement_labels·announcement_fields·llm_calls, attachments.text_engine), `app/config.py`(CLAUDE_*·KORDOC_*), `app/services/labels.py`, `app/services/fields/model.py`·`__init__.py`, `app/automation/settings.py`(새 단계 키).
- 쓰기는 아래 「쓰기 허용」 경로만 합니다. 공용 파일(`app/schema.sql`, `app/db.py`, `app/config.py`, `app/cli.py`, `app/__init__.py`, `app/automation/**`, `app/crawler/**`, `app/services/labels.py`, `app/services/fields/__init__.py`·`model.py`, `requirements.txt`, 문서)은 고치지 않습니다. 필요하면 보고서에 적습니다.
- 「9. 하지 않을 것」을 지킵니다: 실제 Claude API·네트워크·kordoc을 부르는 테스트 금지, `.env` 수정·비밀값 기록 금지, 문서에 없는 기능·관계없는 정리 금지, 커밋 금지(코디네이터가 커밋), 인터넷 사용 금지.
- 테스트: `.venv/Scripts/python -m unittest discover -s tests -q` 전체가 통과해야 합니다(다른 워커가 동시에 작업 중이라 그쪽 테스트가 잠시 깨져 있으면 보고서에 적고 내 테스트만 확인).
- 질문이 생겨도 멈추지 말고 가장 타당한 판단을 한 뒤 보고서에 적습니다.
- 끝나면 `.team/out/w-ui/report.md`를 씁니다: 바꾼 파일과 이유, 테스트 명령과 결과 줄, 계약과 다르게 한 점, 알게 된 문제. **마지막 줄은 `STATUS: DONE`** 입니다.

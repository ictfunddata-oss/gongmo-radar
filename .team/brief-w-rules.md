# 작업 지시 — w-rules

표준 필드 다섯 칸을 규칙으로 찾는 순수 함수를 만듭니다(ADR-051).

## 할 일 (00 6장 3단계 「W-rules」, 5.4 rules 행, 부록 C 전부, 부록 E.3)
- `app/services/fields/rules.py`(+ `sections.py`, `period.py`): `extract(doc) -> dict[str, FieldValue]`. 다섯 칸을 모두 돌려줍니다('해당 없음' 포함, `model.applies` 사용). DB를 읽지 않습니다. `doc`은 `app/services/fields/model.py`의 `Doc`입니다.
- 부록 C.2~C.6·C.8의 정규화·구획 머리·칸별 라벨·기간·기관별 정형 파서·출처 우선순위(사이트 칸 > 본문 > 첨부)를 따릅니다. 배경: `docs/핸드오프/상세화면_표준필드_20261124.md` 4~7장.
- 테스트는 `tests/fixtures/fields/`에 둔 원문 조각으로 합니다: KCA 입찰개요 표(kordoc HTML 표), NIPA 공고문 구획, NIA 본문 일반사항, 목차 줄, 청렴계약 문장, 별지 서식, 두 자리 연도, 기간 충돌(NIPA 16931 같은 경우), '기타' 유형의 해당 없음.
  - 원문 조각은 `data/validation/gold-src/<ann_id>/`(kordoc 결과 `att-*.md`, `body.txt`)에서 짧게 잘라 옮겨도 됩니다(연락처가 없는 부분만).
- `plan/validation/eval_fields.py`(부록 E.3): 정답표 `plan/validation/gold/fields_gold.jsonl`과 예측을 비교해 칸·기관별 채움률·정답률·상태 일치율·인용 불일치 수를 냅니다. 예측은 '규칙만'(gold-src 원문으로 `Doc`을 만들어 `rules.extract`)과 '규칙 + API'(나중에 DB의 announcement_fields)를 고를 수 있게 합니다. 결과는 `plan/validation/gold/report-<이름>.md`.
- 정답표는 W-gold 워커가 지금 만드는 중입니다. `fields_gold.jsonl`이 생기면 규칙만 지표를 보고서에 적고, 아직이면 채움률만 적습니다. **정답표 파일은 읽기만 합니다.**

## 쓰기 허용
- `app/services/fields/rules.py`
- `app/services/fields/sections.py`
- `app/services/fields/period.py`
- `tests/test_fields_rules.py`
- `tests/fixtures/fields/**`
- `plan/validation/eval_fields.py`
- `.team/out/w-rules/**`

## 공통 규칙
- 먼저 `AGENTS.md`·`CLAUDE.md`를 읽습니다. 이 저장소의 테스트는 unittest입니다(pnpm·tsc 없음). 이 PC는 Windows라 가상환경 경로가 `.venv/Scripts/python`입니다(문서의 `.venv/bin/python` 대신).
- 계약은 `plan/00_구현핸드오프.md` 「5장 공통 계약」이 기준입니다. 계약을 바꿔야 할 것 같으면 바꾸지 말고 보고서에 적습니다.
- 2단계 산출물(이미 있음, 읽기만): `app/schema.sql`(announcement_labels·announcement_fields·llm_calls, attachments.text_engine), `app/config.py`(CLAUDE_*·KORDOC_*), `app/services/labels.py`, `app/services/fields/model.py`·`__init__.py`, `app/automation/settings.py`(새 단계 키).
- 쓰기는 아래 「쓰기 허용」 경로만 합니다. 공용 파일(`app/schema.sql`, `app/db.py`, `app/config.py`, `app/cli.py`, `app/__init__.py`, `app/automation/**`, `app/crawler/**`, `app/services/labels.py`, `app/services/fields/__init__.py`·`model.py`, `requirements.txt`, 문서)은 고치지 않습니다. 필요하면 보고서에 적습니다.
- 「9. 하지 않을 것」을 지킵니다: 실제 Claude API·네트워크·kordoc을 부르는 테스트 금지, `.env` 수정·비밀값 기록 금지, 문서에 없는 기능·관계없는 정리 금지, 커밋 금지(코디네이터가 커밋), 인터넷 사용 금지.
- 테스트: `.venv/Scripts/python -m unittest discover -s tests -q` 전체가 통과해야 합니다(다른 워커가 동시에 작업 중이라 그쪽 테스트가 잠시 깨져 있으면 보고서에 적고 내 테스트만 확인).
- 질문이 생겨도 멈추지 말고 가장 타당한 판단을 한 뒤 보고서에 적습니다.
- 끝나면 `.team/out/w-rules/report.md`를 씁니다: 바꾼 파일과 이유, 테스트 명령과 결과 줄, 계약과 다르게 한 점, 알게 된 문제, 규칙만 지표(정답표가 있으면) 또는 채움률. **마지막 줄은 `STATUS: DONE`** 입니다.

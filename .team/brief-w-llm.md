# 작업 지시 — w-llm

Claude API 호출·분류·표준 필드 API 보완을 만듭니다(ADR-045·049). **실제 API는 부르지 않습니다. 모든 테스트는 가짜 클라이언트로 합니다.**

## 할 일 (00 6장 3단계 「W-llm」, 5.4의 llm·classify·fields/api 행, 부록 B 전부)
- `app/services/llm.py`: `PRICES`(부록 B.3), `LLMResult`, `make_client(cfg)`(키가 없으면 RuntimeError, `anthropic.Anthropic(api_key=cfg["CLAUDE_API"])`), `call_json(...)`(`llm_calls` 기록, 거절·잘림은 예외가 아니라 outcome), `submit_batch`, `batch_results`, `cost(model, usage, batch=False)`.
- `app/services/classify.py`: `PROMPT_VERSION = "classify_v2"`, `build_items(conn, ann_ids)`(`plan/validation/make_input.py`와 같은 항목), `input_hash(item)`, `targets`, `run`, `submit_batch`·`collect`, `import_cli(conn, run_dir)`(`run_cli.sh` 결과 폴더 → 라벨, request_id='cli:<실행 이름>'). 저장은 `labels.save_api`(manual 보존). 프롬프트는 `app/prompts/classify_v2.*`.
- `app/services/fields/api.py`와 `app/prompts/extract_v1.system.md`·`extract_v1.schema.json`(부록 B.2): 인용 검사를 통과한 칸만 '확인', 나머지는 method=api인 '미확인'.
- `plan/validation/make_input.py`가 `classify.build_items`를 쓰게 바꿉니다(출력 형식은 그대로: `plan/validation/run_cli.sh`·`evaluate.py`가 읽음).
- SDK: 설치된 `anthropic==1.17.0`의 소스(`.venv/Lib/site-packages/anthropic/`)를 읽어 호출 형태를 확인합니다(`output_config`, beta fallbacks `server-side-fallback-2026-07-01`, Message Batches). 문서(부록 B.3)와 다르면 보고서에 적습니다.
- 테스트(가짜 클라이언트): 정상 / ann_id 빠짐 → 빠진 것만 한 번 다시 → 그래도 없으면 수동 확인 / sub가 class에 안 맞음 / refusal → 분류 보류 / max_tokens → 묶음을 반으로 나눠 다시 / 대체 발생(content에 fallback 블록이 섞임, served_model이 다름) / API 오류 → outcome=error 기록 후 다음 묶음 / manual 라벨 보존 / 같은 input_hash는 다시 보내지 않음 / 일괄 결과 순서가 섞여도 custom_id로 맞춤 / `import_cli`(`data/validation/20261125-v2-low` 구조: `in/<board>/chunk-NN.jsonl`, `out/<board>/chunk-NN.json`의 `structured_output.results`) / 추출 인용 검사 통과·실패 / 비용 계산.

## 쓰기 허용
- `app/services/llm.py`
- `app/services/classify.py`
- `app/services/fields/api.py`
- `app/prompts/extract_v1.*`
- `plan/validation/make_input.py`
- `tests/test_llm.py`
- `tests/test_classify.py`
- `tests/test_fields_api.py`
- `.team/out/w-llm/**`

## 공통 규칙
- 먼저 `AGENTS.md`·`CLAUDE.md`를 읽습니다. 이 저장소의 테스트는 unittest입니다(pnpm·tsc 없음). 이 PC는 Windows라 가상환경 경로가 `.venv/Scripts/python`입니다(문서의 `.venv/bin/python` 대신).
- 계약은 `plan/00_구현핸드오프.md` 「5장 공통 계약」이 기준입니다. 계약을 바꿔야 할 것 같으면 바꾸지 말고 보고서에 적습니다.
- 2단계 산출물(이미 있음, 읽기만): `app/schema.sql`(announcement_labels·announcement_fields·llm_calls, attachments.text_engine), `app/config.py`(CLAUDE_*·KORDOC_*), `app/services/labels.py`, `app/services/fields/model.py`·`__init__.py`, `app/automation/settings.py`(새 단계 키).
- 쓰기는 아래 「쓰기 허용」 경로만 합니다. 공용 파일(`app/schema.sql`, `app/db.py`, `app/config.py`, `app/cli.py`, `app/__init__.py`, `app/automation/**`, `app/crawler/**`, `app/services/labels.py`, `app/services/fields/__init__.py`·`model.py`, `requirements.txt`, 문서)은 고치지 않습니다. 필요하면 보고서에 적습니다.
- 「9. 하지 않을 것」을 지킵니다: 실제 Claude API·네트워크·kordoc을 부르는 테스트 금지, `.env` 수정·비밀값 기록 금지, 문서에 없는 기능·관계없는 정리 금지, 커밋 금지(코디네이터가 커밋), 인터넷 사용 금지.
- 테스트: `.venv/Scripts/python -m unittest discover -s tests -q` 전체가 통과해야 합니다(다른 워커가 동시에 작업 중이라 그쪽 테스트가 잠시 깨져 있으면 보고서에 적고 내 테스트만 확인).
- 질문이 생겨도 멈추지 말고 가장 타당한 판단을 한 뒤 보고서에 적습니다.
- 끝나면 `.team/out/w-llm/report.md`를 씁니다: 바꾼 파일과 이유, 테스트 명령과 결과 줄, 계약과 다르게 한 점, 알게 된 문제. **마지막 줄은 `STATUS: DONE`** 입니다.

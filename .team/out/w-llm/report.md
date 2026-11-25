# w-llm 보고서 — Claude API 호출·분류·표준 필드 API 보완 (3단계)

## 바꾼 파일과 이유

| 파일 | 내용 |
|---|---|
| `app/services/llm.py` (새) | `PRICES`(B.3 단가), `LLMResult`, `make_client(cfg)`(키 없으면 RuntimeError, `anthropic.Anthropic(api_key=cfg["CLAUDE_API"])`), `call_json`(B.3 호출 형태, llm_calls 기록·커밋, 거절·잘림·JSON 아님·API 오류는 outcome으로 돌려줌), `read_message`(stop_reason 먼저, `type=="text"` 블록만 읽음, `usage.iterations`의 `fallback_message` 또는 모델이 다르면 fallback=1), `batch_request`·`submit_batch`·`batch_results`(custom_id로 맞춤, 비용 50%, request_id `batch:<id>`), `cost` |
| `app/services/classify.py` (새) | `PROMPT_VERSION="classify_v2"`, `build_items`, `input_hash`, `targets`, `run`, `submit_batch`·`collect`, `import_cli`. 저장은 `labels.save_api` |
| `app/services/fields/api.py` (새) | `PROMPT_VERSION="extract_v1"`, `sources`, `build_input`, `quote_in`, `supplement` (B.2) |
| `app/prompts/extract_v1.system.md`, `extract_v1.schema.json` (새) | B.2의 역할·칸 정의·규칙 6개·출력. 스키마는 모든 칸 required, `additionalProperties:false`, null 타입 없음 |
| `plan/validation/make_input.py` | 항목을 `classify.build_items`로 만든다. 출력 형식은 같다 |
| `tests/test_llm.py`, `tests/test_classify.py`, `tests/test_fields_api.py` (새) | 가짜 클라이언트(`FakeClient`) 테스트 33개. 네트워크·실제 API 호출 없음 |

## 동작 요약

- **분류(run)**: 50건 묶음 → `call_json(max_tokens=8000)`.
  - ok: 검사를 통과하면 확정. 빠진 ann_id와 class에 맞지 않는 sub는 **그 공고만 한 번** 다시 보낸다. 그래도 안 되면 수동 확인으로 둔다. 빠진 것은 class·sub를 NULL로, sub가 안 맞는 것은 class를 두고 sub를 NULL로 둔다.
  - refusal(대체까지 거절): 분류 보류(class NULL → 화면에서는 '미분류').
  - max_tokens: 묶음을 반으로 나눠 다시 보낸다(재귀, 1건이면 오류로 센다).
  - error·invalid: 저장하지 않고, 기록만 하고 다음 묶음으로 간다. 다음 실행 때 다시 대상이 된다.
  - 라벨의 `model`에는 응답 모델(served_model)을 넣는다.
- **targets**: manual은 늘 뺀다. redo가 아니면 저장된 input_hash가 지금 항목의 해시와 같은 공고도 뺀다. 게시일 최신순으로 돌려준다.
- **일괄 처리**: `submit_batch`가 묶음(custom_id `classify-001`…)과 입력 항목을 `app_kv['llm_batches']`에 JSON 목록으로 남긴다. `collect`는 끝난 배치를 거두고 목록에서 지운다. 거절은 분류 보류로 둔다. 빠진 공고·sub 불일치는 동기로 한 번 다시 보낸다. 잘림·오류는 저장하지 않는다.
- **import_cli**: `in/<board>/chunk-NN.jsonl`과 `out/<board>/chunk-NN.json`의 `structured_output.results`를 읽는다. request_id는 `cli:<폴더 이름>`, model은 meta.txt의 `model=`, prompt_version은 meta.txt의 `prompt=`다. input_hash는 in 파일 항목으로 계산하므로, DB가 그 뒤 바뀌지 않았으면 다시 보내지 않는다.
- **추출 보완(supplement)**:
  - missing 가운데 content·qualify·area·period만 보낸다(title 제외).
  - 원문은 본문 최대 8,000자, 첨부는 `attach_text.pick_files` 순위로 2개까지 각 12,000자, 합계 30,000자다. 연락처는 가리고 writer는 넣지 않는다.
  - 인용은 HTML 태그·공백·마크다운 기호를 무시하고 그 source_id 원문에 들어 있어야 '확인'이 된다. 아니면 '미확인'에 note '인용 불일치'를 단다.
  - API가 ok가 아니면 보낸 칸 모두 '미확인'에 note `API <outcome>`을 단다. 돌려주는 칸은 모두 `method='api'`, `prompt_version='extract_v1'`이다.

## 테스트

```
.venv/Scripts/python -m unittest tests.test_llm tests.test_classify tests.test_fields_api
Ran 33 tests in 0.223s
OK

.venv/Scripts/python -m unittest discover -s tests -q
Ran 188 tests in 6.798s
OK
```

브리프의 테스트 항목은 모두 들어 있다. 항목별 테스트 이름은 다음과 같다.

| 항목 | 테스트 |
|---|---|
| 정상 | `RunTest.test_ok`, `CallJsonTest.test_ok_request_shape_and_record`(호출 형태·기록·비용) |
| ann_id 빠짐 → 한 번 다시 → 수동 확인 | `test_missing_retried_once_then_manual` |
| sub 불일치 | `test_bad_sub` |
| refusal → 분류 보류 | `test_refusal_is_hold` |
| max_tokens → 반으로 나눠 다시 | `test_max_tokens_splits` |
| 대체 발생 | `test_fallback_served`, `test_fallback_model_recorded` |
| API 오류 → outcome=error, 다음 묶음 | `test_api_error_is_outcome`, `test_api_error_then_next_chunk` |
| manual 보존 | `test_manual_kept`, `ImportCliTest` |
| 같은 input_hash 재전송 안 함 | `TargetsTest` |
| 일괄 결과 순서 섞임 | `llm BatchTest.test_results_matched_by_custom_id`, `classify BatchTest` |
| import_cli | `ImportCliTest.test_import`, `test_real_run_dir_if_present`(실제 폴더가 있으면 형식만 확인) |
| 추출 인용 검사 통과·실패 | `SupplementTest.test_quote_passes`·`test_quote_fails` |
| 비용 계산 | `CostTest` |

테스트 밖에서 확인한 것(scratchpad 테스트, 저장소에는 넣지 않음):

- 실제 DB(읽기 전용)로 `build_items`를 돌리면 `data/validation/20261125-v2-low/in`의 1,090건과 항목이 **모두 같다**. make_input 출력 형식이 그대로라는 뜻이다.
- 실제 DB의 **임시 사본**에 `import_cli(20261125-v2-low)`를 돌렸다. 결과는 1,090건 모두 확정(공모지원사업 214 · 입찰공고 743 · 기타 133)이고, 빠짐·실패 묶음은 0이다. 가져온 뒤 `targets()`는 0건이었다. 원본 `data/gongmo.db`는 건드리지 않았다.

## SDK 확인 (anthropic 1.17.0, `.venv/Lib/site-packages/anthropic/`)

부록 B.3과 다른 점은 없다.

- `client.beta.messages.create`는 `fallbacks`(`"default"` 또는 목록)와 `output_config`(`effort`·`format`)를 받는다. `server-side-fallback-2026-07-01`은 `AnthropicBetaParam`에 있다.
- 대체가 일어나면 `content`에 `type=="fallback"` 블록(`from_`/`to`/`trigger`)이 섞인다. SDK 문서는 대체 여부를 블록이 아니라 `usage.iterations`의 `type=="fallback_message"` 항목(`model` 포함)으로 판단하라고 한다. 그래서 두 신호와 `response.model` 비교를 모두 본다.
- `stop_reason`에 `refusal`·`max_tokens`가 있다. `_request_id`는 응답 최상위 객체에 있다.
- 일괄 처리: `client.messages.batches.create(requests=[{custom_id, params}])`, `.retrieve(id).processing_status`(`ended`), `.results(id)`가 `custom_id`와 `result.type`(succeeded/errored/canceled/expired)을 돌려준다. SDK docstring도 "결과 순서는 보장되지 않으니 custom_id로 맞추라"고 적고 있다.
- 예외: `RateLimitError`·`APIStatusError`·`APIConnectionError` 모두 `anthropic.*`에 있다. HTTP 라이브러리는 `httpx`가 아니라 `httpx2`다(테스트에서 `httpx2.Request` 사용).

## 계약과 다르게 했거나 정한 점

1. **`llm.submit_batch` 시그니처**: 5.4에는 `submit_batch(...)`로만 적혀 있어서 `submit_batch(cfg, requests, *, client=None) -> batch_id`로 정했다. `batch_results(conn, cfg, batch_id, *, stage, items=None, run_id=None, client=None)`는 끝나지 않았으면 None, 끝났으면 `{custom_id: LLMResult}`를 돌려준다. 요청 한 건은 `llm.batch_request(cfg, custom_id, ...)`로 만든다.
2. **`classify.submit_batch(conn, cfg, ann_ids, *, client=None, say=print)`와 `collect(conn, cfg, *, run_id=None, client=None, say=print)`**: `app_kv['llm_batches']`에 쓰고 읽는 일을 classify 안에서 한다(5.5에서는 CLI가 남긴다고 했다). 묶음별 ann_id·input_hash가 있어야 거둘 수 있기 때문이다. 값 형식은 `[{"id", "stage": "classify", "submitted_at", "chunks": {custom_id: [항목...]}}]`이고, 다른 stage 항목은 건드리지 않는다. cli.py(4단계)는 이 두 함수만 부르면 된다.
3. **`classify.run`의 반환값**: `{"items", "calls", "확정", "수동 확인", "분류 보류", "kept_manual", "errors", "cost_usd"}`. collect는 여기에 `batches`·`pending`을 더한다. import_cli는 `{"items", "확정", "수동 확인", "missing", "failed_chunks", "kept_manual", "unknown"}`을 돌려준다. 키 없음은 `run`·`collect`에서 `make_client`가 RuntimeError를 낸다. '키 없음'으로 건너뛰는 판단은 pipeline 쪽에서 한다.
4. **다시 보냈는데 그 호출이 error·잘림이면**: 첫 응답 기준으로 수동 확인으로 둔다(다시 거절이면 분류 보류).
5. **`llm.record`는 호출마다 커밋한다.** 비용 기록이 부르는 쪽의 rollback에 사라지지 않게 하려는 것이다. 다만 `fields.run`이 supplement 전에 save한 규칙 행도 그때 같이 커밋된다. `fields.run`의 커밋 직전이라 영향은 거의 없다.
6. **period 날짜**: `fields/period.py`(W-rules)가 아직 없다(보고서 작성 시점에 파일 없음). 그래서 `api._dates`는 `crawler.adapters.nia.extract_period`로 읽는다. 이 함수는 '접수기간·신청기간·모집기간·공고기간…' 같은 라벨이 있어야 읽는다. **4단계에서 period.py의 공개 함수 이름이 정해지면 `_dates` 한 곳을 바꿔야 한다.**
7. **첨부 연락처 가림**: B.2는 본문만 '연락처 가림'이라고 했지만 첨부 글자에도 `mask_contacts`를 적용했다. 인용 검사도 가린 원문으로 하므로 저장되는 value도 가려진 글이다. 화면 규칙(CLAUDE.md 「데이터 규칙」)에 맞추려는 것이다.
8. **classify input_hash**에는 프롬프트 판이 들어가지 않는다. 프롬프트를 바꾼 뒤 다시 분류하려면 `--redo`를 써야 한다.

## 알게 된 문제

- **`mask.mask_contacts`가 공백 없이 긴 글에서 매우 느리다.** 이메일 정규식 `[\w.+-]+@`가 한글도 `\w`로 잡아 O(n²)이 된다. 공백 없는 5만 자에서 20초 넘게 걸렸다. api.py에서는 먼저 자르고 가리는 방식으로 피했다. mask.py는 공용 파일이라 고치지 않았다. attach_text 등 다른 곳에서 긴 글을 가린다면 같은 문제가 생길 수 있다.
- `attach_text.pick_files`는 `extract.SUPPORTED`(hwp·hwpx·pdf·docx)에 없는 확장자를 버린다. W-kordoc이 zip 행에 `text_status='ok'`를 주더라도, pick_files가 zip을 받지 않는 한 extract_v1 입력에 zip 글자는 들어가지 않는다. W-kordoc이 pick_files를 바꾸는지 4단계에서 확인해야 한다.
- 테스트의 메모리 DB를 닫지 않아 ResourceWarning이 나온다. 기존 테스트(test_labels 등)와 같은 방식이고, 실패는 아니다.
- `data/validation/20261125-v2-low`는 1,090건이다(00 문서에는 1,010건).

STATUS: DONE

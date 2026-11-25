# 작업 지시 — w-gold

당신은 상세화면 표준 필드의 **정답표 초안**을 만드는 워커입니다. 표본 45건 × 5칸 = 225줄을 씁니다.

## 읽을 것
1. `plan/00_구현핸드오프.md`의 「부록 E.2 정답표」(형식·규칙)와 「5.6 코드표」(칸·상태·출처 값)
2. `docs/핸드오프/상세화면_표준필드_20261124.md`의 「4.2 필드 정의」「4.4 출처 우선순위」「6. 추출할 때 주의할 점」
3. `app/prompts/classify_v2.system.md` — 공고 유형(class) 판단 기준(v2)
4. `plan/validation/gold/gold_notes.md` — 표본 45건 목록(ann_id·게시판·게시물 번호)

## 원문
공고마다 `data/validation/gold-src/<ann_id>/`에 있습니다.
- `meta.json`: 제목·말머리(biz)·사이트 기간(period_raw, start_at, end_at)·게시일·기준 분류(ref_class, v1 이전 기준이라 참고만)
- `body.txt`: 사이트 본문(연락처는 가려져 있음)
- `att-NN.md`, `att-NN-KK.md`(zip 안 파일): 첨부를 kordoc으로 읽은 글. `attachments.json`에 파일 이름과 읽기 결과가 있습니다. 못 읽은 첨부(이미지·실패)는 없는 것으로 봅니다.

## 할 일
1. 공고마다 class를 v2 기준으로 정합니다(애매하면 memo에 이유).
2. 다섯 칸(title, content, qualify, area, period)마다 한 줄씩 `plan/validation/gold/fields_gold.jsonl`에 씁니다. 형식은 부록 E.2 예시와 같습니다:
   `{"ann_id": …, "board": …, "post_no": …, "class": …, "field": …, "status": "확인|미확인|해당 없음", "key": …, "source": "site|body|attachment", "source_ref": …, "start_at": …, "end_at": …, "reviewed": false, "memo": ""}`
   - key: 정답 판정에 쓸 **원문 그대로의 구절 20~60자**. 그 칸 구획의 첫 문장 일부를 옮깁니다(띄어쓰기·기호는 원문대로). period는 key를 null로 두고 start_at·end_at(YYYY-MM-DD)을 씁니다.
   - source는 4.4 우선순위(사이트 칸 > 본문 > 첨부)에서 그 값을 처음 찾은 곳, source_ref는 첨부면 파일 이름, 아니면 null.
   - 미확인: 원문 어디에도 없음. 해당 없음: 유형상 없는 칸(예: 기타 유형의 qualify). 확인이 아니면 key·start_at·end_at은 null.
   - title은 사이트 제목에서 앞 말머리를 뗀 것이 key입니다.
3. 파일을 다 쓴 뒤 직접 다시 읽어 줄 수가 225(=표본 수 × 5)인지, ann_id마다 다섯 칸이 하나씩 있는지 확인합니다.
4. `.team/out/w-gold/report.md`를 씁니다: 처리 건수, class별 건수, 칸별 상태 건수, 판단이 어려웠던 공고(ann_id·칸·이유), 원문 품질 문제(읽지 못한 첨부 등). **마지막 줄은 `STATUS: DONE`** 입니다.

## 지켜야 할 것
- 쓰기는 `plan/validation/gold/fields_gold.jsonl`과 `.team/out/w-gold/` 안에서만 합니다. `gold_notes.md`·코드·DB·문서는 고치지 않습니다.
- 추출 코드(`app/services/fields/`)나 그 결과는 보지 않습니다. 원문만 보고 판단합니다.
- 셸 명령과 인터넷은 쓰지 않습니다.
- 질문이 생겨도 멈추지 말고 가장 타당한 판단을 한 뒤 memo와 report.md에 적습니다.

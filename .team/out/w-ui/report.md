# W-ui 보고서 — 3단계 화면(부록 D)

## 바꾼 파일과 이유
- `app/services/public.py` (D.1·D.2): `SQL`에 `LEFT JOIN announcement_labels`(class·sub). `build_item`에 `type`(`labels.public_type`). `public_item`에 `sub`(미분류면 None)·`fields`. `fields`는 `standard_fields()`가 만든다: `fields.load` 행이 하나도 없으면 `[]`(→ '아직 정리하지 않은 공고'), 있으면 FIELDS 순서 다섯 줄. 행이 빠진 칸은 유형에 있는 칸이면 '미확인', 없는 칸이면 '해당 없음'으로 채운다. 줄마다 `label`(`model.LABELS[유형]`)과 `source_text`('사이트 칸'/'공고 본문'/'첨부: 파일명', api면 '· AI 발췌'). `_structs`·`astruct`·`astruct_data`와 `raw_view` import를 수요자 경로에서 뺐다.
- `app/static/public.js` (D.1): `GROUPS`에 `ty`(전체·공모지원사업·입찰공고·기타·미분류). 기본·초기화 상태는 {공모지원사업, 미분류}이고, 이때 '공모지원사업' 버튼이 선택돼 보이며 '조건 적용 중'에 세지 않는다. '공모지원사업' 건수에는 미분류가 들어간다. 카드에 기관 배지 다음 유형 배지, '첨부 구조화' 칩 삭제.
- `app/static/public.css`: 유형 배지(공모지원사업 강조색, 입찰공고·기타 회색, 미분류 점선)와 '공고 표준 정보' 표 스타일을 끝에 추가.
- `app/templates/public/detail.html` (D.2): 머리에 유형 배지·하위 유형. '첨부 공고문에서 읽어 정리한 내용' 블록 자리에 '공고 표준 정보'(확인: 값, 400자 넘으면 `<details>`, 출처 / 미확인: '원문 확인 필요' + 원문·`#files` 링크 / 해당 없음: 흐리게 / 충돌: note). 첨부 박스에 `id="files"`. `|safe` 없음.
- `app/services/admin_labels.py` (새 파일, D.3): `org_types`·`label_status`·`pending`·`field_status`·`conflicts`·`api_usage`(이번 달·지난달 단계별 합계·대체·실패)·`recent_calls`(20건).
- `app/web/admin.py`: `GET /admin/labels`(`admin.labels_view`), `POST /admin/notice/<ann_id>/label`(`labels.set_manual`, 잘못된 값은 ValueError → 경고 메시지, 없는 공고 404). 운영 상세에 label·표준 필드 전달. 자동화 저장이 새 스위치 4개·상한 3개를 `settings.clean()`에 넘긴다(상한 칸이 폼에 없으면 기본값).
- `app/templates/admin/labels.html`(새), `admin/base.html`(메뉴 '분류·정리'), `admin/detail.html`(현재 라벨·유형 수정 양식·표준 필드 표: evidence·method·note 포함), `admin/automation.html`(②③④·④ API 보완 스위치와 실행당 상한 3개).
- 테스트: `tests/test_public_item.py`에 `TypeAndFieldsTest` 4건, `tests/test_admin_labels.py`(새) 11건.

## 테스트
- `.venv/Scripts/python -m unittest tests.test_public_item tests.test_admin_labels -q` → `Ran 22 tests ... OK`
- `.venv/Scripts/python -m unittest discover -s tests -q` → `Ran 155 tests in 12.902s` / `OK` (다른 워커 변경 포함한 작업 트리 기준)
- 출력에 `EOF marker not found` 한 줄이 섞여 나오지만 실패는 아니다(제 테스트가 아닌 쪽에서 나오는 것으로 보임).
- `public.js`는 이 칸에서 `node --check`가 권한상 막혀 문법 검사를 하지 못했다. diff를 눈으로 확인했고, 브라우저 확인은 7단계에서 데이터를 채운 뒤 필요하다.

## 계약과 다르게 한 점·판단
- 유형 수정 POST 주소는 부록 D.3대로 `/admin/notice/<ann_id>/label`이고, 운영 상세 GET은 기존 `/admin/announcements/<ann_id>` 그대로다(경로 접두가 다름). 처리 뒤 운영 상세로 되돌린다.
- 유형 수정 폼은 `cls`·`sub` 두 선택칸이다. 맞지 않는 조합은 `set_manual`이 거부하고 화면에 경고를 띄운다.
- 운영 이력은 `set_manual`이 이미 남기므로 라우트에서는 따로 `_audit`을 부르지 않았다(중복 기록 방지).
- '전체' 유형 버튼(조건 없음)은 '조건 적용 중'에 세지 않았다. 세는 것은 입찰공고·기타·미분류를 골랐을 때뿐이다.
- 표준 필드의 period 칸은 value가 비고 start_at/end_at만 있으면 'start ~ end'로 보여 준다.
- 공개 API·엑셀 내보내기·`raw_view`(운영 원본 화면)는 건드리지 않았다.

## 알게 된 문제
- `public.css`의 `.prep.att` 등 '첨부 구조화' 칩 스타일은 이제 수요자 화면에서 쓰지 않는다. 관계없는 정리라 지우지 않았다.
- 자동화 화면 '실행 기록' 요약은 아직 수집 결과만 보여 준다. ②~④ 단계 요약 표시는 파이프라인 summary 키가 정해지는 4단계에서 같이 붙이는 게 좋겠다.
- 상한 입력값 1000 초과는 `clean()`이 1000으로 잘라 저장한다(오류 메시지 없음). 테스트에서 이 동작을 고정했다.

STATUS: DONE

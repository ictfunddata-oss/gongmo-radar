# w-gold

## 소유
- 쓰기: `plan/validation/gold/fields_gold.jsonl`, `.team/out/w-gold/**` (이 워커만)
- 읽기 전용: `data/validation/gold-src/**`, `plan/validation/gold/gold_notes.md`, `plan/00_구현핸드오프.md`, `docs/핸드오프/상세화면_표준필드_20261124.md`, `app/prompts/classify_v2.system.md`
- 코디네이터 소유(워커 쓰기 금지): `plan/validation/gold/gold_notes.md`, 앱 코드·DB·문서 전체, `.team/*.md`

## 맡은 일
정답표 초안 — 표본 45건 × 5칸(00 부록 E.2)

## 칸
- 모델·effort: claude-opus-5-5 · high (45건 원문을 읽고 정답을 판단한다. 틀리면 이후 모든 지표가 틀린다)
- 칸 핸들: (띄운 뒤 적음)

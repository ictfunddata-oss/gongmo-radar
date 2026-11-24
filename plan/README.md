# plan — 배포 파이프라인 계획

**구현을 맡길 때는 `00_구현핸드오프.md` 하나만 넘긴다.** 첫 메시지는 그 문서의 부록 A다.

| 파일 | 내용 |
|---|---|
| `00_구현핸드오프.md` | 구현 핸드오프(단일 문서): 결정, 시작 조건, 공통 계약(표·설정·함수·명령), 0~7단계와 검증, Orca 분업, 관문 기준, 프롬프트·규칙·화면 명세 |
| `01_핸드오프_배포파이프라인.md` | 배경: 현재 상태, 설계 근거, 비용 추정, 분류 v1 CLI 검증 결과, 결정 사항 |
| `02_메타프롬프트_파이프라인구현.md` | (대체됨) 이전 구현 지시문. 00으로 합쳤다 |
| `03_kordoc_도입검토.md` | 첨부(HWP·HWPX·PDF) 읽기에 kordoc을 넣을 수 있는지 판단, 실측 비교 |
| `prompts/classify_v1.system.md` · `classify_v1.schema.json` | 분류 v1 프롬프트와 출력 스키마(이력). v2부터는 `app/prompts/`에 둔다(00 2.3) |
| `validation/run_cli.sh` · `make_input.py` · `evaluate.py` | 프롬프트를 Claude Code CLI(`claude -p`)로 기관별 묶음마다 돌려 검증한다. 결과는 `data/validation/`(git 제외) |

관련 문서
- `docs/핸드오프/상세화면_표준필드_20261124.md`: 상세화면 표준 필드 분석
- `.team/out/summary.md`: 유형 분류 통계(Orca 분할 실행)

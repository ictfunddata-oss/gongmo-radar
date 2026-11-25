# W-kordoc 보고서

## 바꾼 파일
- `app/services/kordoc.py`(새 파일): `to_text(path, cfg) -> (text|None, status)`. 상태: ok / empty / timeout / error:<사유>. `KORDOC_ENABLED`가 꺼져 있으면 실행하지 않음(`error:꺼져 있음`). `shlex.split(KORDOC_CMD)` 첫 인자를 `shutil.which`로 찾음(Windows `npx.cmd`). 임시 폴더를 cwd로 씀, `--ocr` 없음. 출력은 `extract.MAX_CHARS`에서 자르고 `MIN_USEFUL` 미만이면 empty. 시간 초과면 `_kill_tree`(Windows `taskkill /T /F`, 그 밖은 `os.killpg`) 뒤 `communicate()`.
- `app/services/extract.py`: `read_text(path, ext, cfg) -> (text, status, engine)` 추가. sniff 결과가 hwp/hwpx/pdf/docx이고 kordoc이 켜져 있으면 kordoc 먼저, ok가 아니면 `extract_text`(engine='legacy'). 기존 `extract_text`는 손대지 않음.
- `app/services/attach_text.py`:
  - `pick_files(rows, limit, readable=SUPPORTED+("zip",))`: zip도 후보. 같은 이름(확장자 뺀 이름, 대소문자 무시)의 hwp/hwpx가 있으면 pdf는 뺌. 점수가 같으면 hwp/hwpx를 먼저 읽음.
  - `targets(..., any_body=False)`: True면 본문 길이와 상관없이 대상.
  - `read_zip(path, cfg)`(부록 C.7): 임시 폴더에 풀고 끝나면 지움. 앞 50개 항목만 보고, 0x800 플래그 없는 이름은 cp437→cp949로 다시 해석. 절대경로·드라이브·`..` 이름은 건너뜀(풀 때 안의 이름은 경로로 쓰지 않고 `NN.ext`로 저장). 풀린 크기 합 상한은 `ATTACH_MAX_MB`(머리의 크기와 실제 읽은 양 둘 다 확인). `pick_files` 점수로 최대 2개를 `read_text`로 읽고, `### <안의 이름>` 머리를 붙여 이음. engine은 처음 읽은 파일의 엔진, 하나라도 읽으면 ok.
  - `process()`: zip은 `read_zip`, 나머지는 `extract.read_text`. `text_engine` 저장(ok일 때만, 아니면 NULL). `text_status` 값의 뜻은 그대로.
- `tests/test_kordoc.py`(새 파일): 성공(표 줄 유지, 인자에 --ocr 없음, cwd 지정), MAX_CHARS 자르기, 0이 아닌 종료, 시간 초과(트리 종료 호출), 빈 출력, 꺼짐, 명령 없음 / read_text: kordoc 우선, error·timeout·empty → legacy로 넘어감, 꺼짐·unsupported면 kordoc 부르지 않음.
- `tests/test_attach_text.py`: any_body, hwp·pdf 중복 제거(pick_files와 zip 안 모두), zip 후보, zip 안 cp949 이름(UTF-8 플래그 없는 zip을 바이트로 만듦), `../`·절대경로 거부, 크기 상한, process가 zip 글자·text_engine 저장. 기존 시험은 그대로.

## 테스트
- `.venv/Scripts/python -m unittest tests.test_kordoc tests.test_attach_text` → `Ran 32 tests ... OK`
- `.venv/Scripts/python -m unittest discover -s tests -q` → `Ran 140 tests in 11.966s` / `OK` (ResourceWarning: 닫지 않은 DB 경고는 원래 있던 것)

## 계약과 다르게 한 점
- 명세의 `subprocess.run(..., timeout=...)` 대신 `subprocess.Popen` + `communicate(timeout)` + `_kill_tree`를 씀. `run`은 시간이 지나면 부모(npx.cmd)만 끝내고, 출력 관을 쥔 node 자식 때문에 Windows에서 멈춤(브리프의 Windows 주의, 참고 구현 `dump_gold_src.py`와 같은 방식). 그래서 시험도 `subprocess.run`이 아니라 `kordoc.subprocess.Popen`을 가짜로 바꿈.
- kordoc이 꺼져 있을 때 `to_text`는 `(None, "error:꺼져 있음")`. `read_text`는 미리 확인해서 아예 부르지 않음. cfg에 키가 없으면 꺼진 것으로 봄(`cfg.get("KORDOC_ENABLED")`; 실제 설정은 config.py가 기본값 1로 넣음).
- zip이 아닌데 `ext='zip'`인 행이나 깨진 zip은 `error:BadZipFile: …`. 안에 읽을 파일이 없으면 `unsupported`.

## 실제 확인(테스트 밖, 한 번)
`.venv/Scripts/flask --app run attach-text --ann-id <id> --redo --no-download`, DB는 `.venv/Scripts/python -c`로 읽음.

| 공고 | ann_id | 읽은 첨부 | text_status / text_engine | 표 |
|---|---|---|---|---|
| KCA 6239644 (kca_bidding) | 35 | seq2 입찰공고문.hwp, seq4 제품규격….hwp(같은 이름의 pdf seq1·3은 고르지 않음) | ok / kordoc (6,221자, 8,988자) | HTML `<table>` 2개, 8개(+마크다운 표 줄 19개) — rowspan·th 유지 |
| NIPA 17006 (hwpx) | 1 | seq1 모집 공고문.hwpx | ok / kordoc (5,684자) | HTML 표 4개, 마크다운 표 줄 7개 (추진 일정 표 칸·날짜 유지) |
| NIPA 16953 | 7 | seq1 [공고문].hwp, seq2 [참가신청서].hwp | ok / kordoc (3,022자, 2,613자) | HTML 표 2개, 1개 |

- **NIPA 16953(ann_id 7)에는 DB에 zip 첨부가 없음**(hwp 두 개뿐). 그래서 실제 zip 확인은 다른 공고의 zip(ann_id 5, NIPA 16967 「…입주기업 모집 공고문 및 신청서.zip」)을 `attach_text.read_zip`으로 DB에 쓰지 않고 읽어 봄: 안의 이름 4개가 한글로 바르게 나왔고(pdf·doc·docx 2개), 서식 파일을 빼고 공고문.pdf·사업계획서.docx 2개를 골라 ok. 이때 엔진은 legacy였음. 같은 pdf를 kordoc으로 따로 읽으니 ok, **46.9초**(docx는 4.0초). 첫 실행 때(npx 준비 시간 포함) 60초를 넘겨 timeout → 기존 추출기로 넘어간 것으로 보임. 넘어가는 동작 자체는 설계대로임.
- 위 세 공고는 본문 길이와 상관없이 `--ann-id`로 지정해서 읽혔음(`--any-body`가 필요 없었음).

## 알게 된 문제 (내 범위 밖)
1. **`app/cli.py:86` attach-text 마지막 요약 출력이 Windows(cp949 콘솔)에서 `UnicodeEncodeError: 'cp949' codec can't encode character '\u2014'`로 끝남.** 처리·commit은 그 전에 끝나서 DB에는 저장됨. 다만 종료 코드가 1이라 cron·스크립트에서는 실패로 보임. `—`를 빼거나 `PYTHONIOENCODING=utf-8`로 해결 가능(코디네이터 소유 파일).
2. kordoc의 PDF 처리가 느림(위 46.9초). 첫 npx 실행에는 패키지 준비 시간도 더해짐. 컨테이너에서는 전역 설치(`KORDOC_CMD=kordoc`)라 덜하겠지만, 큰 PDF에는 `KORDOC_TIMEOUT=60`이 빠듯할 수 있음.
3. kordoc 출력에는 `**` 강조·`![image](…)` 줄·HTML 표가 그대로 들어 있음. 부록 C(536행)의 강조 지우기·표 줄 바꾸기는 fields 쪽(W-rules) 일로 보고 여기서는 원문 markdown을 그대로 저장함.
4. 공고 7의 「참가신청서.hwp」도 읽힘. 기존 `_score`에서 '신청서'(−4)와 '공고/모집'(+3)이 상쇄돼 0점이라 서식으로 걸러지지 않음(기존 동작, 바꾸지 않음).

STATUS: DONE

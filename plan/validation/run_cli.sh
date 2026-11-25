#!/usr/bin/env bash
# 분류 프롬프트 검증 — 분류 프롬프트(기본 app/prompts/classify_v2.*)를 Claude Code CLI(claude -p)로 기관별 묶음마다 돌린다.
#   plan/validation/run_cli.sh                      # 4개 기관 전체
#   ORGS="nipa_business kca_bidding" plan/validation/run_cli.sh
#   MODEL=claude-sonnet-5-5 EFFORT=low CHUNK=50 PAR=6 RUN=data/validation/이름 plan/validation/run_cli.sh
#   PROMPT_BASE=plan/prompts/classify_v1 plan/validation/run_cli.sh   # 이전 판(v1)으로 다시 재기
# 배포 파이프라인이 API로 보낼 것과 같은 시스템 프롬프트·JSON 스키마를 쓴다.
# 데이터가 든 입력·출력은 data/validation/ 아래(.gitignore 대상)에 쌓는다.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
if [ -x "$ROOT/.venv/bin/python" ]; then PY="${PY:-$ROOT/.venv/bin/python}"; else PY="${PY:-$ROOT/.venv/Scripts/python.exe}"; fi   # Windows 가상환경은 Scripts/
export PYTHONUTF8=1           # Windows 기본 인코딩(cp949)으로 한글 입출력이 깨지지 않게 한다
MODEL="${MODEL:-claude-sonnet-5-5}"
EFFORT="${EFFORT:-low}"
CHUNK="${CHUNK:-50}"
PAR="${PAR:-6}"
ORGS="${ORGS:-nipa_business nia_bid kca_bidding rapa_notice}"
RUN="${RUN:-data/validation/$(date +%Y%m%d-%H%M%S)}"
RUN="$(mkdir -p "$RUN" && cd "$RUN" && pwd)"
PROMPT_BASE="${PROMPT_BASE:-app/prompts/classify_v2}"
PROMPT="$ROOT/$PROMPT_BASE.system.md"
SCHEMA="$(cat "$ROOT/$PROMPT_BASE.schema.json")"
WORK="$(mktemp -d)"          # 저장소 밖에서 실행해 프로젝트 CLAUDE.md·설정이 섞이지 않게 한다
trap 'rm -rf "$WORK"' EXIT

"$PY" plan/validation/make_input.py --out "$RUN/in" --chunk "$CHUNK" --org $ORGS
if command -v shasum >/dev/null; then SHA="shasum -a 256"; else SHA="sha256sum"; fi
printf 'model=%s\neffort=%s\nchunk=%s\nprompt=%s\nprompt_sha=%s\n' "$MODEL" "$EFFORT" "$CHUNK" "$(basename "$PROMPT_BASE")" "$($SHA "$PROMPT" | cut -c1-12)" > "$RUN/meta.txt"

one() {                       # $1 = 입력 묶음 파일
  local in="$1" org out
  org="$(basename "$(dirname "$in")")"
  out="$RUN/out/$org/$(basename "$in" .jsonl).json"
  mkdir -p "$(dirname "$out")"
  { printf '다음 items를 분류하세요.\n<items>\n'; "$PY" -c 'import json,sys; print(json.dumps([json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()], ensure_ascii=False))' "$in"; printf '</items>\n'; } \
    | (cd "$WORK" && claude -p --model "$MODEL" --effort "$EFFORT" --system-prompt-file "$PROMPT" --json-schema "$SCHEMA" \
         --output-format json --tools "" --strict-mcp-config --setting-sources project --disable-slash-commands --no-session-persistence) \
    > "$out" 2> "$out.err" || echo "실패: $in" >&2
  echo "끝: $org/$(basename "$in")"
}
export -f one
export RUN WORK PY MODEL EFFORT PROMPT SCHEMA
find "$RUN/in" -name 'chunk-*.jsonl' | sort | xargs -P "$PAR" -I{} bash -c 'one "$@"' _ {}
"$PY" plan/validation/evaluate.py "$RUN"

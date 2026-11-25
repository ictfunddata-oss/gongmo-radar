#!/usr/bin/env bash
# 표준 필드 API 보완 프롬프트 검증 — app/prompts/extract_v1.* 를 Claude Code CLI(claude -p)로 공고 1건 = 1호출로 돌린다.
#   1) flask --app run extract-fields --dump-input data/validation/<실행> --ann-id ...   (입력 만들기: <실행>/in/<ann_id>.txt·.json)
#   2) RUN=data/validation/<실행> plan/validation/run_extract_cli.sh                   (결과: <실행>/out/<ann_id>.json)
#   3) flask --app run extract-fields --import-cli data/validation/<실행>             (인용 검사 뒤 DB에 넣기)
#   MODEL=claude-sonnet-5-5 EFFORT=low PAR=6 PROMPT_BASE=app/prompts/extract_v1 로 바꿀 수 있다.
# run_cli.sh와 같이 저장소 밖 빈 폴더에서 도구·MCP·프로젝트 설정 없이 돌린다. 데이터는 data/validation/(git 제외).
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
MODEL="${MODEL:-claude-sonnet-5-5}"
EFFORT="${EFFORT:-low}"
PAR="${PAR:-6}"
RUN="${RUN:?RUN=data/validation/<실행> 을 주세요(먼저 --dump-input 으로 입력을 만듭니다)}"
RUN="$(cd "$RUN" && pwd)"
PROMPT_BASE="${PROMPT_BASE:-app/prompts/extract_v1}"
PROMPT="$ROOT/$PROMPT_BASE.system.md"
SCHEMA="$(cat "$ROOT/$PROMPT_BASE.schema.json")"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if command -v shasum >/dev/null; then SHA="shasum -a 256"; else SHA="sha256sum"; fi
printf 'model=%s\neffort=%s\nprompt=%s\nprompt_sha=%s\n' "$MODEL" "$EFFORT" "$(basename "$PROMPT_BASE")" "$($SHA "$PROMPT" | cut -c1-12)" > "$RUN/meta.txt"
mkdir -p "$RUN/out"

one() {                       # $1 = 입력 파일(<ann_id>.txt)
  local in="$1" out
  out="$RUN/out/$(basename "$in" .txt).json"
  (cd "$WORK" && claude -p --model "$MODEL" --effort "$EFFORT" --system-prompt-file "$PROMPT" --json-schema "$SCHEMA" \
     --output-format json --tools "" --strict-mcp-config --setting-sources project --disable-slash-commands --no-session-persistence) \
    < "$in" > "$out" 2> "$out.err" || echo "실패: $in" >&2
  echo "끝: $(basename "$in")"
}
export -f one
export RUN WORK MODEL EFFORT PROMPT SCHEMA
find "$RUN/in" -name '*.txt' | sort | xargs -P "$PAR" -I{} bash -c 'one "$@"' _ {}

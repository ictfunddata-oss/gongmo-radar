#!/usr/bin/env bash
# 공모사업 수집 웹앱 개발 서버 실행
#   ./run-app.sh             → http://127.0.0.1:5001
#   PORT=8000 ./run-app.sh   → 다른 포트로
# macOS는 5000번을 제어 센터(AirPlay 수신)가 쓰고 있어 기본 포트를 5001로 둔다.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-5001}"

# 가상환경: 없으면 만들고, 처음이거나 requirements.txt 가 바뀌었으면 설치한다
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/pip install -q -r requirements.txt
  touch .venv/.installed
fi

# 설정 파일이 없으면 예시를 복사한다
if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env 가 없어 .env.example 을 복사했습니다."
fi
if ! grep -Eq '^ADMIN_PASSWORD_HASH=.+' .env; then
  echo "운영 화면(/admin)을 쓰려면 먼저: .venv/bin/flask --app run set-admin-password"
fi

echo "수요자 화면 http://127.0.0.1:${PORT}/  ·  운영 화면 http://127.0.0.1:${PORT}/admin"
exec .venv/bin/flask --app run run --host 127.0.0.1 --port "${PORT}" --debug

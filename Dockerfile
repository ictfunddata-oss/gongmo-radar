# 공모사업 수집 웹앱 — 이미지 하나(Python 3.12 + Node 20 + kordoc), 서비스 둘(web·worker)은 docker-compose.yml (ADR-046)
FROM node:20-bookworm-slim AS node

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Node 20과 kordoc(첨부 HWP·HWPX·PDF 읽기, ADR-050). 버전을 고정하고 OCR 모델은 넣지 않는다
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && npm i -g kordoc@4.24.59 --no-audit --no-fund \
 && npm cache clean --force

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# 비루트 사용자. 데이터(SQLite·첨부·내보내기)는 볼륨 /data
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown -R app:app /data
USER app
ENV DATA_DIR=/data ATTACHMENT_DIR=/data/attachments EXPORT_DIR=/data/exports KORDOC_CMD=kordoc
VOLUME ["/data"]
EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "wsgi:app"]

"""여러 테스트가 같이 쓰는 도구 — 스키마 문자열."""
from pathlib import Path

SCHEMA = (Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text(encoding="utf-8")

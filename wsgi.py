"""운영 진입점 — gunicorn wsgi:app. 개발 서버(run.py, flask --app run)와 달리 SECRET_KEY가 안전한지 먼저 확인한다."""
from app import create_app
from app.config import check_secret, load_config

check_secret(load_config())   # 앱을 만들기 전에 확인해 예약 실행기 등이 뜨지 않게 한다
app = create_app()

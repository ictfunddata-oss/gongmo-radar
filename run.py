"""개발 서버 실행:  python run.py   (관리 명령은  flask --app run <명령>)"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

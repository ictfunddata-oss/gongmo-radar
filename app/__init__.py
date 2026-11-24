"""공모사업 수집 웹앱 (Flask 애플리케이션 팩토리)."""
from flask import Flask

from . import cli, db
from .config import load_config


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(load_config())
    if overrides:
        app.config.update(overrides)
    for key in ("DATA_DIR", "ATTACHMENT_DIR", "EXPORT_DIR"):
        app.config[key].mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    cli.init_app(app)

    from .web import BLUEPRINTS
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    if overrides is None:   # 테스트(overrides 있음)에서는 예약 실행기를 띄우지 않는다
        from .automation import scheduler
        if scheduler.should_autostart(app.config):
            scheduler.start(app)
    return app

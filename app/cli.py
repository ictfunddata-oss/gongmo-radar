"""관리 명령 — `flask --app run <명령>` 으로 실행한다(README 참고)."""
import json
from pathlib import Path

import click
from flask import current_app

from .crawler import crawl, fetch_attachments
from .crawler.adapters import ADAPTERS
from .db import connect, init_schema
from .services.export import export_xlsx
from .services.export_json import export_json
from .services.legacy import migrate_legacy

DEFAULT_BOARD = "nipa_business"


def _conn():
    return connect(current_app.config["DB_PATH"])


@click.command("init-db")
def init_db_cmd():
    """DB 스키마를 만든다(이미 있으면 그대로 둔다)."""
    with _conn() as conn:
        init_schema(conn)
    click.echo(f"DB 준비 완료: {current_app.config['DB_PATH']}")


@click.command("boards")
def boards_cmd():
    """등록된 게시판 어댑터 목록."""
    for code, cls in ADAPTERS.items():
        click.echo(f"{code:20} {cls.org_name} · {cls.board_name} · {cls.list_url}")


@click.command("crawl")
@click.option("--board", default=DEFAULT_BOARD, show_default=True, help="게시판 코드(flask boards 참고)")
@click.option("--full", is_flag=True, help="전체 쪽 수집(기본은 새 글만 받는 증분 수집)")
@click.option("--pages", type=int, help="앞에서부터 N쪽만 수집")
@click.option("--no-attachments", is_flag=True, help="이번 실행에서 첨부를 받지 않음")
@click.option("--start-page", type=int, default=1, show_default=True, help="이 쪽부터 수집(중단된 전체 수집 재개용)")
@click.option("--skip-known", is_flag=True, help="본문까지 이미 받은 공고는 다시 읽지 않음")
def crawl_cmd(board, full, pages, no_attachments, start_page, skip_known):
    """공고를 수집한다. 신규 공고의 첨부는 수집 시점에 즉시 저장한다."""
    with _conn() as conn:
        res = crawl(conn, current_app.config, board, mode="full" if full else "incremental",
                    pages=pages, download=False if no_attachments else None, start_page=start_page, skip_known=skip_known)
    click.echo(json.dumps(res, ensure_ascii=False))


@click.command("fetch-attachments")
@click.option("--board", default=DEFAULT_BOARD, show_default=True)
@click.option("--since", help="이 게시일(YYYY-MM-DD) 이후 공고만")
@click.option("--limit", type=int, help="최대 공고 수")
def fetch_attachments_cmd(board, since, limit):
    """이미 수집한 공고 중 첨부를 아직 받지 않은 것을 받는다(상세 페이지를 다시 읽음)."""
    with _conn() as conn:
        n = fetch_attachments(conn, current_app.config, board, since=since, limit=limit)
    click.echo(f"첨부 {n}개 저장")


@click.command("attach-text")
@click.option("--limit", type=int, default=10, show_default=True, help="최대 공고 수")
@click.option("--since", help="이 게시일(YYYY-MM-DD) 이후 공고만")
@click.option("--board", help="게시판 코드로 한정")
@click.option("--ann-id", type=int, multiple=True, help="특정 공고만")
@click.option("--redo", is_flag=True, help="이미 읽어 본 공고도 다시 읽기")
@click.option("--no-download", is_flag=True, help="새로 받지 않고 이미 저장된 파일에서만 글자를 뽑기")
@click.option("--dry-run", is_flag=True, help="읽을 공고와 파일 목록만 보여 주고 받거나 저장하지 않음")
def attach_text_cmd(limit, since, board, ann_id, redo, no_download, dry_run):
    """본문이 짧은 공고의 첨부 공고문(HWP·HWPX·PDF·DOCX)을 받아 글자를 뽑아 저장해 둔다. 외부 서비스는 쓰지 않는다."""
    from .services import attach_text
    cfg = current_app.config
    with _conn() as conn:
        ids = attach_text.targets(conn, cfg, since=since, board_code=board, limit=limit, ann_ids=list(ann_id), redo=redo)
        click.echo(f"대상 공고 {len(ids)}건{' · dry-run' if dry_run else ''}")
        for aid in ids:
            a = conn.execute("SELECT title, posted_at FROM announcements WHERE ann_id=?", (aid,)).fetchone()
            files = attach_text.pick_files([dict(x) for x in conn.execute("SELECT seq, name, ext, file_path FROM attachments WHERE ann_id=? ORDER BY seq", (aid,))],
                                           cfg["ATTACH_TEXT_FILES"])
            click.echo(f"  #{aid} {a['posted_at'] or ''} {a['title'][:40]} → " + ", ".join(f"{f['name'][:28]}{'' if f['file_path'] else '(받아야 함)'}" for f in files))
        if dry_run or not ids:
            return
        res = attach_text.process(conn, cfg, ids, download=not no_download)
        click.echo("결과 — " + " · ".join(f"{k} {v}" for k, v in res.items()))


@click.command("migrate-legacy")
@click.option("--source", type=click.Path(exists=True, dir_okay=False), help="기존 nipa.db 경로(기본: LEGACY_DB_PATH)")
def migrate_legacy_cmd(source):
    """기존 NIPA 수집 DB를 새 스키마로 옮기고 건수를 대조한다."""
    src = source or current_app.config["LEGACY_DB_PATH"]
    with _conn() as conn:
        res = migrate_legacy(conn, src)
    for table, (before, after) in res.items():
        click.echo(f"{table:14} 원본 {before:>5} → 이관 {after:>5} {'✓' if before == after else '✗ 불일치'}")


@click.command("export-json")
@click.option("--out", default=None, help="내보낼 폴더(기본 data/json)")
def export_json_cmd(out):
    """수집한 공고를 공고 1건 = JSON 1개로 내보낸다."""
    with _conn() as conn:
        res = export_json(conn, out or current_app.config["DATA_DIR"] / "json")
    click.echo(json.dumps(res, ensure_ascii=False))


@click.command("export")
def export_cmd():
    """공고·첨부 목록을 엑셀로 내보낸다(EXPORT_DIR)."""
    with _conn() as conn:
        out = export_xlsx(conn, current_app.config["EXPORT_DIR"])
    click.echo(f"저장: {out}")


@click.command("set-admin-password")
@click.option("--generate", is_flag=True, help="무작위 비밀번호를 만들어 data/admin_initial_password.txt 에 저장한다(화면에는 출력하지 않음)")
def set_admin_password_cmd(generate):
    """관리자 비밀번호를 설정한다. 해시만 .env 에 저장하고, 서명 키(SECRET_KEY)가 짧거나 기본값이면 새로 만든다."""
    import secrets

    from . import auth
    from .config import BASE_DIR
    env = BASE_DIR / ".env"
    if generate:
        password = secrets.token_urlsafe(12)
    else:
        password = click.prompt("새 관리자 비밀번호(10자 이상)", hide_input=True, confirmation_prompt=True)
        if len(password) < 10:
            raise click.ClickException("비밀번호는 10자 이상이어야 합니다.")
    updates = {"ADMIN_PASSWORD_HASH": "'" + auth.make_hash(password) + "'"}
    key = current_app.config["SECRET_KEY"]
    if len(key) < 32 or key == "dev-only-change-me":
        updates["SECRET_KEY"] = auth.random_secret()
    auth.set_env(env, updates)
    if generate:
        out = Path(current_app.config["DATA_DIR"]) / "admin_initial_password.txt"
        out.write_text(f"관리자 아이디: {current_app.config['ADMIN_ID']}\n초기 비밀번호: {password}\n"
                       "로그인한 뒤 `flask --app run set-admin-password` 로 바꾸고 이 파일을 지우세요.\n", encoding="utf-8")
        click.echo(f"초기 비밀번호를 {out} 에 저장했습니다. 서버를 다시 켜면 적용됩니다.")
    else:
        click.echo("관리자 비밀번호를 저장했습니다. 서버를 다시 켜면 적용됩니다.")


@click.command("automation-run")
@click.option("--force", is_flag=True, help="설정에서 자동 실행이 꺼져 있어도 실행한다")
def automation_run_cmd(force):
    """저장된 자동화 설정대로 수집 파이프라인을 한 번 실행한다. 작업 스케줄러(cron·Windows 작업 스케줄러)용."""
    from .automation import settings as cfgmod
    from .automation.pipeline import run_pipeline
    with _conn() as conn:
        s = cfgmod.load(conn)
    if not s["enabled"] and not force:
        raise click.ClickException("자동 실행이 꺼져 있습니다. 운영 화면 '자동화'에서 켜거나 --force 로 실행하세요.")
    res = run_pipeline(dict(current_app.config), "명령", settings=s)
    if res is None:
        raise click.ClickException("이미 다른 곳에서 실행 중입니다.")
    run_id, status, summary = res
    click.echo(f"실행 #{run_id} · {status} · {json.dumps(summary, ensure_ascii=False)}")


@click.command("automation-daemon")
def automation_daemon_cmd():
    """예약 실행기만 따로 돌린다(웹 서버와 분리 배포할 때). 웹 쪽은 AUTOMATION_SCHEDULER=0 으로 둔다."""
    from .automation import scheduler
    click.echo("예약 실행기를 시작합니다. 종료는 Ctrl+C")
    try:
        scheduler.loop(dict(current_app.config))
    except KeyboardInterrupt:
        click.echo("종료")


def init_app(app):
    for cmd in (set_admin_password_cmd, init_db_cmd, boards_cmd, crawl_cmd, fetch_attachments_cmd, attach_text_cmd, migrate_legacy_cmd, export_cmd, export_json_cmd, automation_run_cmd, automation_daemon_cmd):
        app.cli.add_command(cmd)

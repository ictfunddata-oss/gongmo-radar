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
@click.option("--any-body", is_flag=True, help="본문이 긴 공고도 첨부를 읽음(표준 필드용)")
def attach_text_cmd(limit, since, board, ann_id, redo, no_download, dry_run, any_body):
    """본문이 짧은 공고의 첨부 공고문(HWP·HWPX·PDF·DOCX)을 받아 글자를 뽑아 저장해 둔다. 외부 서비스는 쓰지 않는다."""
    from .services import attach_text
    cfg = current_app.config
    with _conn() as conn:
        ids = attach_text.targets(conn, cfg, since=since, board_code=board, limit=limit, ann_ids=list(ann_id), redo=redo, any_body=any_body)
        click.echo(f"대상 공고 {len(ids)}건{' · dry-run' if dry_run else ''}")
        for aid in ids:
            a = conn.execute("SELECT title, posted_at FROM announcements WHERE ann_id=?", (aid,)).fetchone()
            files = attach_text.pick_files([dict(x) for x in conn.execute("SELECT seq, name, ext, file_path FROM attachments WHERE ann_id=? ORDER BY seq", (aid,))],
                                           cfg["ATTACH_TEXT_FILES"])
            click.echo(f"  #{aid} {a['posted_at'] or ''} {a['title'][:40]} → " + ", ".join(f"{f['name'][:28]}{'' if f['file_path'] else '(받아야 함)'}" for f in files))
        if dry_run or not ids:
            return
        res = attach_text.process(conn, cfg, ids, download=not no_download)
        click.echo("결과: " + " · ".join(f"{k} {v}" for k, v in res.items()))   # '—'는 Windows 콘솔(cp949)에서 깨진다


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


def _echo_res(res):
    click.echo(json.dumps(res, ensure_ascii=False, default=str))


@click.command("classify")
@click.option("--board", help="게시판 코드로 한정")
@click.option("--limit", type=int, help="최대 공고 수")
@click.option("--redo", is_flag=True, help="이미 분류한 공고도 다시(사람이 고친 값은 그대로)")
@click.option("--dry-run", is_flag=True, help="묶음 수·건수·추정 입력 토큰만 보여 주고 API를 부르지 않음")
@click.option("--batch", "batch", is_flag=True, help="일괄 처리로 제출(50% 할인, 결과는 --collect로)")
@click.option("--collect", is_flag=True, help="끝난 일괄 처리를 거둬 저장")
@click.option("--import-cli", "import_dir", type=click.Path(exists=True, file_okay=False), help="run_cli.sh 결과 폴더를 라벨로 넣음(API 비용 없음)")
def classify_cmd(board, limit, redo, dry_run, batch, collect, import_dir):
    """공고 유형을 분류한다(Claude API, classify_v2). 사람이 고친 값은 덮어쓰지 않는다."""
    from .services import classify
    cfg = current_app.config
    with _conn() as conn:
        if import_dir:
            return _echo_res(classify.import_cli(conn, Path(import_dir)))
        try:
            if collect:
                return _echo_res(classify.collect(conn, cfg, say=click.echo))
            ids = classify.targets(conn, board=board, limit=limit, redo=redo)
            if dry_run:
                items = classify.build_items(conn, ids)
                chunks = [items[i:i + classify.CHUNK] for i in range(0, len(items), classify.CHUNK)]
                chars = sum(len(classify.user_text(c)) for c in chunks) + len(classify.prompt()[0]) * len(chunks)
                return click.echo(f"대상 {len(items)}건 · 묶음 {len(chunks)}개 · 추정 입력 토큰 약 {chars // 2:,}(글자 수 ÷ 2) · API 호출 안 함")
            if batch:
                return click.echo(f"배치 제출: {classify.submit_batch(conn, cfg, ids, say=click.echo) or '대상 없음'}")
            _echo_res(classify.run(conn, cfg, ids, say=click.echo))
        except RuntimeError as e:      # make_client: 키 없음
            raise click.ClickException(str(e)) from None


@click.command("extract-fields")
@click.option("--board", help="게시판 코드로 한정")
@click.option("--limit", type=int, help="최대 공고 수")
@click.option("--ann-id", type=int, multiple=True, help="특정 공고만(여러 번)")
@click.option("--redo", is_flag=True, help="입력이 같아도 다시 정리")
@click.option("--api", is_flag=True, help="공모지원사업의 미확인 칸을 API로 보완")
@click.option("--dry-run", is_flag=True, help="대상 건수만 보여 줌")
@click.option("--batch", "batch", is_flag=True, help="API 보완을 일괄 처리로 제출(규칙 정리를 먼저 돌린 공고)")
@click.option("--collect", is_flag=True, help="끝난 일괄 처리를 거둬 저장")
@click.option("--dump-input", "dump_dir", type=click.Path(file_okay=False), help="API에 보낼 입력을 파일로만 씀(CLI 검증용)")
@click.option("--import-cli", "import_dir", type=click.Path(exists=True, file_okay=False), help="CLI 추출 결과를 넣음")
def extract_fields_cmd(board, limit, ann_id, redo, api, dry_run, batch, collect, dump_dir, import_dir):
    """상세화면 표준 다섯 칸을 정리한다. 기본은 규칙만, --api면 공모지원사업의 미확인 칸을 API로 보완한다."""
    from .services import fields
    cfg = current_app.config
    with _conn() as conn:
        if import_dir:
            return _echo_res(fields.import_cli(conn, Path(import_dir)))
        try:
            if collect:
                return _echo_res(fields.collect(conn, cfg))
            ids = list(ann_id) or fields.targets(conn, board=board, limit=limit, redo=redo)
            if dry_run:
                return click.echo(f"대상 {len(ids)}건{' · API 보완 대상은 규칙 정리 뒤 정해짐' if api else ''}")
            if dump_dir:
                return click.echo(f"입력 {fields.dump_input(conn, list(ann_id) or fields.targets(conn, board=board, limit=limit, redo=True), dump_dir)}건 → {dump_dir}")
            if batch:
                return click.echo(f"배치 제출: {fields.submit_batch(conn, cfg, list(ann_id) or fields.targets(conn, board=board, limit=limit, redo=True)) or '대상 없음'}")
            if api and not cfg.get("CLAUDE_API"):
                raise click.ClickException("CLAUDE_API 키가 없어 API 보완을 할 수 없습니다(규칙만 돌리려면 --api 없이).")
            _echo_res(fields.run(conn, cfg, ids, api=api, api_max=limit or 50, redo=redo, say=click.echo))
        except RuntimeError as e:
            raise click.ClickException(str(e)) from None


def init_app(app):
    for cmd in (set_admin_password_cmd, init_db_cmd, boards_cmd, crawl_cmd, fetch_attachments_cmd, attach_text_cmd, migrate_legacy_cmd, export_cmd, export_json_cmd, automation_run_cmd, automation_daemon_cmd,
                classify_cmd, extract_fields_cmd):
        app.cli.add_command(cmd)

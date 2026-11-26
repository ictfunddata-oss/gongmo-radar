"""kordoc CLI로 첨부 글자를 마크다운으로 읽는다(ADR-050). 표가 마크다운·HTML 표로 살아 나온다.

- `to_text(path, cfg)` → (텍스트 또는 None, 상태). 상태: ok / empty / timeout / error:<사유>
- OCR(`--ocr`)은 쓰지 않는다. 실패하면 부르는 쪽(`extract.read_text`)이 기존 추출기로 넘어간다.
- Windows의 `npx`는 `npx.cmd`라 `shutil.which`로 찾는다. 시간을 넘기면 node 자식까지 끝낸다(그러지 않으면 출력 관을 쥔 채 남아 기다림이 끝나지 않는다).
"""
import os
import shlex
import shutil
import subprocess
import tempfile

from . import extract


def _kill_tree(p):
    """시간을 넘긴 kordoc을 자식 프로세스까지 끝낸다."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        os.killpg(p.pid, 9)


def _command(cfg, path):
    args = shlex.split(cfg["KORDOC_CMD"])
    args[0] = shutil.which(args[0]) or args[0]
    return args + [str(path)]


def to_text(path, cfg):
    """kordoc으로 파일을 읽는다. 표준 출력(markdown)을 extract.MAX_CHARS에서 자른다. 예외를 밖으로 내보내지 않는다."""
    if not cfg.get("KORDOC_ENABLED"):
        return None, "error:꺼져 있음"
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            p = subprocess.Popen(_command(cfg, path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp,
                                 start_new_session=os.name != "nt")
            try:
                out, err = p.communicate(timeout=cfg.get("KORDOC_TIMEOUT", 60))
            except subprocess.TimeoutExpired:
                _kill_tree(p)
                p.communicate()
                return None, "timeout"
    except OSError as e:                     # 명령을 찾지 못함 등
        return None, f"error:{type(e).__name__}: {str(e)[:120]}"
    if p.returncode != 0:
        lines = (err or b"").decode("utf-8", "replace").strip().splitlines()
        return None, "error:" + (lines[-1][:200] if lines else f"exit {p.returncode}")
    text = (out or b"").decode("utf-8", "replace").strip()
    if len(text) < extract.MIN_USEFUL:
        return None, "empty"
    return text[:extract.MAX_CHARS], "ok"

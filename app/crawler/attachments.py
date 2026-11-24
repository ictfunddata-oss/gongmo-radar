"""첨부파일 다운로드.

첨부 링크의 토큰은 접속마다 바뀌므로, 상세 페이지를 읽은 바로 그 세션에서 즉시 받는다.
저장 위치: {ATTACHMENT_DIR}/{게시판코드}/{게시물번호}/{순번:02d}_{파일명}
"""
import hashlib
import re
from pathlib import Path
from urllib.parse import unquote

from .utils import now_iso, safe_filename


def filename_from_disposition(header):
    """Content-Disposition 에서 파일명 추출(filename* 우선, URL 인코딩 해제)."""
    if not header:
        return None
    m = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", header)
    if not m:
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', header)
    return unquote(m.group(1).strip()) if m else None


def download(http, att, board_code, post_no, root, max_mb):
    """첨부 1개를 받아 저장하고 DB에 넣을 값(dict)을 돌려준다. 실패하면 download_error 만 채운다."""
    tmp = None
    try:
        r = http.get(att["url"], stream=True, timeout=60)
        name = filename_from_disposition(r.headers.get("Content-Disposition")) or att.get("name") or f"file_{att['seq']}"
        rel = Path(board_code) / str(post_no) / f"{att['seq']:02d}_{safe_filename(name)}"
        dest = Path(root) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        limit, size, h = max_mb * 1024 * 1024, 0, hashlib.sha256()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                size += len(chunk)
                if size > limit:
                    raise ValueError(f"용량 상한 초과({max_mb:.0f}MB)")
                h.update(chunk)
                f.write(chunk)
        r.close()
        tmp.replace(dest)
        return {"file_path": rel.as_posix(), "file_size": size, "sha256": h.hexdigest(),
                "downloaded_at": now_iso(), "download_error": None}
    except Exception as e:  # 첨부 하나 실패로 수집 전체를 멈추지 않는다
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        return {"download_error": f"{type(e).__name__}: {e}"[:300]}

"""첨부 공고문에서 글자를 뽑는다(HWP·HWPX·PDF·DOCX). 외부 서비스 없이 이 컴퓨터 안에서만 처리한다.

- 결과는 (텍스트, 상태)다. 상태: ok / empty(글자 없음: 스캔본 등) / encrypted(암호·배포용 문서) / unsupported(처리하지 않는 형식) / error:<이유>
- HWP(5.x)는 OLE 파일 안의 BodyText 구역을 직접 읽는다. 표·글상자 안의 글자도 문단으로 들어 있어 함께 뽑힌다. 그림 속 글자는 못 뽑는다.
- 표 서식·그림·각주는 복원하지 않는다. 글자만 순서대로 이어 붙인다.
"""
import re
import struct
import zipfile
import zlib
from pathlib import Path

SUPPORTED = ("hwp", "hwpx", "pdf", "docx")
MAX_CHARS = 60000        # 한 파일에서 저장할 최대 글자 수
MAX_PDF_PAGES = 40       # PDF 는 앞 40쪽까지만 읽는다
MIN_USEFUL = 30          # 이보다 적게 뽑히면 글자가 없는 파일(스캔본 등)로 본다

# HWP 문단 글자 안의 제어 문자: 1글자짜리, 그리고 뒤에 14바이트가 더 붙는 것(확장·인라인)
_ONE_CHAR = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}
_WIDE = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
_TAG_PARA_TEXT = 67      # HWPTAG_PARA_TEXT (HWPTAG_BEGIN 16 + 51)


def _clean(text):
    text = text.encode("utf-8", "ignore").decode("utf-8")       # 짝 없는 서로게이트 등 저장할 수 없는 조각 제거
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t 　]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── HWP ──
def _join_utf16(text):
    """UTF-16 조각으로 나뉜 글자 쌍(이모지 등)을 합치고, 짝이 없는 조각은 바꿈 문자로 치환한다."""
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def hwp_para_texts(stream):
    """풀어 놓은 BodyText 구역 바이트에서 문단 글자를 차례로 돌려준다."""
    out, i, n = [], 0, len(stream)
    while i + 4 <= n:
        head = struct.unpack_from("<I", stream, i)[0]
        i += 4
        tag, size = head & 0x3FF, (head >> 20) & 0xFFF
        if size == 0xFFF:
            if i + 4 > n:
                break
            size = struct.unpack_from("<I", stream, i)[0]
            i += 4
        data = stream[i:i + size]
        i += size
        if tag != _TAG_PARA_TEXT:
            continue
        chars, j = [], 0
        while j + 2 <= len(data):
            code = struct.unpack_from("<H", data, j)[0]
            if code < 32:
                if code in (10, 13):
                    chars.append("\n")
                elif code in _WIDE:
                    j += 14
                elif code not in _ONE_CHAR:
                    pass
                j += 2
                continue
            chars.append(chr(code))
            j += 2
        out.append(_join_utf16("".join(chars)))
    return out


def _hwp(path):
    import olefile
    if not olefile.isOleFile(str(path)):
        return "", "error:HWP 형식이 아님(HWPX일 수 있음)"
    ole = olefile.OleFileIO(str(path))
    try:
        header = ole.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File"):
            return "", "error:HWP 머리글이 없음"
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 0b10 or flags & 0b100:           # 암호 · 배포용 문서(본문이 ViewText에 암호화되어 있음)
            return "", "encrypted"
        compressed = bool(flags & 1)
        sections = sorted((e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
                          key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
        parts = []
        for e in sections:
            raw = ole.openstream(e).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            parts.extend(hwp_para_texts(raw))
        return "\n".join(parts), "ok"
    finally:
        ole.close()


# ── HWPX / DOCX (zip 안의 XML) ──
def _xml_text(xml_bytes, para_tag, text_tag):
    from lxml import etree
    root = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False))
    paras = []
    for p in root.iter():
        if isinstance(p.tag, str) and etree.QName(p).localname == para_tag:
            t = "".join((x.text or "") for x in p.iter() if isinstance(x.tag, str) and etree.QName(x).localname == text_tag)
            paras.append(t)
    return "\n".join(paras)


def _hwpx(path):
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                       key=lambda n: int(re.sub(r"\D", "", n) or 0))
        if not names:
            return "", "error:HWPX 본문 구역이 없음"
        return "\n".join(_xml_text(z.read(n), "p", "t") for n in names), "ok"


def _docx(path):
    with zipfile.ZipFile(path) as z:
        return _xml_text(z.read("word/document.xml"), "p", "t"), "ok"


# ── PDF ──
def _pdf(path):
    from pypdf import PdfReader
    r = PdfReader(str(path))
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:  # noqa: BLE001
            return "", "encrypted"
    out, total = [], 0
    for page in r.pages[:MAX_PDF_PAGES]:           # 앞쪽 쪽수만 읽는다(공고문 핵심은 앞부분, 전체를 읽으면 오래 걸린다)
        t = page.extract_text() or ""
        out.append(t)
        total += len(t)
        if total > MAX_CHARS * 1.2:
            break
    return "\n".join(out), "ok"


def sniff(path):
    """확장자가 아니라 파일 앞부분으로 형식을 알아낸다. → hwp / hwpx / docx / pdf / zip / unknown
    (사이트가 .hwpx 로 올린 파일이 실제로는 .hwp 이거나 HTML 인 경우가 있다)"""
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if any(n.startswith("Contents/section") for n in names):
            return "hwpx"
        if "word/document.xml" in names:
            return "docx"
        return "zip"
    return "unknown"


_READERS = {"hwp": _hwp, "hwpx": _hwpx, "pdf": _pdf, "docx": _docx}


def extract_text(path, ext=None):
    """파일에서 글자를 뽑는다. → (텍스트, 상태). 어떤 파일이어도 예외를 밖으로 내보내지 않는다.
    ext 는 참고용이며 실제 형식은 파일 내용으로 정한다."""
    p = Path(path)
    try:
        kind = sniff(p)
    except OSError as e:
        return "", f"error:{type(e).__name__}: {str(e)[:120]}"
    if kind not in _READERS:
        return "", "unsupported"
    try:
        text, status = _READERS[kind](p)
    except Exception as e:  # noqa: BLE001 — 깨진 파일 하나가 전체 작업을 멈추지 않게
        return "", f"error:{type(e).__name__}: {str(e)[:120]}"
    if status != "ok":
        return "", status
    text = _clean(text)
    if len(text) < MIN_USEFUL:
        return text, "empty"
    return text[:MAX_CHARS], "ok"


def read_text(path, ext, cfg):
    """kordoc을 먼저 쓰고, 실패하면 extract_text 로 읽는다. → (텍스트, 상태, 엔진: kordoc / legacy)"""
    from . import kordoc
    try:
        kind = sniff(Path(path))
    except OSError:
        kind = "unknown"
    if cfg.get("KORDOC_ENABLED") and kind in _READERS:
        text, status = kordoc.to_text(path, cfg)
        if status == "ok":
            return text, status, "kordoc"
    text, status = extract_text(path, ext)
    return text, status, "legacy"

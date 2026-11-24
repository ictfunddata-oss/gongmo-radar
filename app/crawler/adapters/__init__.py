"""기관 어댑터 등록부 — 새 기관은 어댑터 파일을 만들고 여기에 한 줄 추가한다."""
from .kca import KcaBiddingAdapter
from .nia import NiaBidAdapter
from .nipa import NipaBusinessAdapter
from .rapa import RapaNoticeAdapter

ADAPTERS = {cls.code: cls for cls in (NipaBusinessAdapter, NiaBidAdapter, RapaNoticeAdapter, KcaBiddingAdapter)}


def get_adapter_class(code):
    try:
        return ADAPTERS[code]
    except KeyError:
        raise KeyError(f"등록되지 않은 게시판 코드: {code} (사용 가능: {', '.join(ADAPTERS)})") from None

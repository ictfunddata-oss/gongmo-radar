"""기관 어댑터 기반 클래스 — 기관 게시판 하나 = 어댑터 하나.

어댑터는 '게시판마다 다른 부분'(URL, HTML 파싱)만 담는다.
요청 간격·재시도·저장·첨부 다운로드는 runner/attachments 가 공통으로 처리한다.

목록 행(dict) 표준 키: post_no, list_no, site_status, title, biz, period_raw, writer, list_date
상세(dict) 표준 키:   biz, period_raw, writer, posted_at, views, body,
                      files=[{seq, name, ext, size_text, size_bytes, url}]
"""
from abc import ABC, abstractmethod


class BoardAdapter(ABC):
    code = ""          # 게시판 코드(유일), 예: nipa_business
    org_code = ""      # 예: nipa
    org_name = ""      # 예: 정보통신산업진흥원
    org_kind = "전담기관"
    board_name = ""    # 예: 사업공고
    list_url = ""
    since = None       # 'YYYY-MM-DD' — 이 날짜 이전 공고는 저장하지 않는다(없으면 전체)

    def __init__(self, http):
        self.http = http

    # ── 네트워크 ──
    def fetch_list(self, page):
        return self.parse_list(self.http.get(self.list_page_url(page)).text, page)

    def fetch_detail(self, post_no):
        return self.parse_detail(self.http.get(self.detail_url(post_no)).text)

    def is_pinned(self, row):
        """상단 고정 공지 여부 — 날짜 순서에서 벗어나므로 since 판단·중단 판단에서 제외한다."""
        return False

    # ── 게시판별 구현 ──
    @abstractmethod
    def list_page_url(self, page): ...

    @abstractmethod
    def detail_url(self, post_no): ...

    @abstractmethod
    def parse_list(self, html, page):
        """→ (목록 행 list, 마지막 쪽 번호)"""

    @abstractmethod
    def parse_detail(self, html):
        """→ 상세 dict"""

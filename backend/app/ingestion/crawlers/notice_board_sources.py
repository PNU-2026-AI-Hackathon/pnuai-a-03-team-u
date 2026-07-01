"""로그인 없이 접근 가능한 부산대 공지사항 게시판 설정.

같은 CMS 엔진을 쓰는 사이트는 site_id/board_id 등 설정값만 다르게 주면
notice_board_crawler.py의 동일한 파서로 크롤링할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtclViewSource:
    """`artclView.do` 계열 CMS. 부산대 산하 다수 기관 사이트가 이 엔진을 쓴다.

    목록은 POST `{base_url}/bbs/{site_id}/{board_id}/artclList.do`,
    상세는 `{base_url}/bbs/{site_id}/{board_id}/{article_seq}/artclView.do`.
    """

    name: str
    site_id: str
    board_id: str
    base_url: str

    @property
    def list_url(self) -> str:
        return f"{self.base_url}/bbs/{self.site_id}/{self.board_id}/artclList.do"

    def detail_url(self, article_seq: str) -> str:
        return f"{self.base_url}/bbs/{self.site_id}/{self.board_id}/{article_seq}/artclView.do"


@dataclass(frozen=True)
class CmsBoardSource:
    """부산대 본부 `CMS/Board.do` 게시판."""

    name: str
    base_url: str
    m_code: str
    mgr_seq: str

    @property
    def list_url(self) -> str:
        return f"{self.base_url}/kor/CMS/Board/Board.do"

    def detail_url(self, board_seq: str) -> str:
        return f"{self.list_url}?mCode={self.m_code}&mode=view&mgr_seq={self.mgr_seq}&board_seq={board_seq}"


ARTCL_VIEW_SOURCES: list[ArtclViewSource] = [
    ArtclViewSource(
        name="swedu", site_id="swedu", board_id="2265", base_url="https://swedu.pusan.ac.kr"
    ),
    ArtclViewSource(
        name="uitc", site_id="uitc", board_id="1518", base_url="https://uitc.pusan.ac.kr"
    ),
    ArtclViewSource(
        name="pnucounsel",
        site_id="pnucounsel",
        board_id="1174",
        base_url="https://pnucounsel.pusan.ac.kr",
    ),
    ArtclViewSource(
        name="ctl", site_id="ctl", board_id="1701", base_url="https://ctl.pusan.ac.kr"
    ),
]

CMS_BOARD_SOURCES: list[CmsBoardSource] = [
    CmsBoardSource(
        name="pusan_main", base_url="https://www.pusan.ac.kr", m_code="MN095", mgr_seq="3"
    ),
]


@dataclass(frozen=True)
class LibPyxisSource:
    """도서관 Pyxis CMS. JSON API(`pyxis-api`)를 그대로 페이지네이션한다."""

    name: str
    base_url: str
    board_id: str

    @property
    def bulletins_api_url(self) -> str:
        return f"{self.base_url}/pyxis-api/1/bulletin-boards/{self.board_id}/bulletins"

    def detail_url(self, bulletin_id: str) -> str:
        return f"{self.base_url}/guide/notice/{bulletin_id}"


@dataclass(frozen=True)
class JobBoardSource:
    """취업전략과 공지사항(`/ko/notice/notice`) 게시판."""

    name: str
    base_url: str

    def list_url(self, page: int) -> str:
        return f"{self.base_url}/ko/notice/notice/list/{page}"

    def detail_url(self, article_id: str) -> str:
        return f"{self.base_url}/ko/notice/notice/view/{article_id}"


LIB_PYXIS_SOURCES: list[LibPyxisSource] = [
    LibPyxisSource(name="lib", base_url="https://lib.pusan.ac.kr", board_id="2"),
]

JOB_BOARD_SOURCES: list[JobBoardSource] = [
    JobBoardSource(name="job", base_url="https://job.pusan.ac.kr"),
]

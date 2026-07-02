"""부산대 공지사항 게시판(비교과 활동 공고 출처)을 크롤링한다.

로그인이 필요한 my.pusan.ac.kr 개인화 페이지 대신, 로그인 없이 보이는
공개 게시판(학과/부속기관 공지)에서 활동 공고를 모은다. 게시판은 최신순
정렬이므로, 비고정 게시글의 작성일이 lookback_days보다 오래되면 그
페이지에서 페이지네이션을 멈춘다.

DB 매핑은 이 모듈의 책임이 아니다 — normalizer가 NoticeRow를
domains 모델로 변환한다.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from app.ingestion.crawlers.notice_board_sources import (
    ARTCL_VIEW_SOURCES,
    CMS_BOARD_SOURCES,
    JOB_BOARD_SOURCES,
    LIB_PYXIS_SOURCES,
    ArtclViewSource,
    CmsBoardSource,
    JobBoardSource,
    LibPyxisSource,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)
DEFAULT_LOOKBACK_DAYS = 90
MAX_PAGES = 200


@dataclass(frozen=True)
class NoticeRow:
    source: str
    title: str
    url: str
    author: str
    posted_date: str  # ISO date (YYYY-MM-DD)
    views: int | None
    is_pinned: bool


def _parse_date(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text.strip().replace(".", "-"))


def _parse_int(text: str | None) -> int | None:
    text = (text or "").strip()
    return int(text) if text.isdigit() else None


def fetch_artcl_view_page(source: ArtclViewSource, page: int) -> list[NoticeRow]:
    response = requests.post(
        source.list_url,
        data={"page": str(page)},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    rows: list[NoticeRow] = []
    for tr in soup.select("table.board-table tbody tr"):
        title_cell = tr.select_one(".td-title a")
        if title_cell is None:
            continue
        for badge in title_cell.select(".new"):
            badge.decompose()
        href = title_cell.get("href", "")
        match = re.search(r"/(\d+)/artclView\.do", href)
        article_seq = match.group(1) if match else ""
        date_cell = tr.select_one(".td-date")
        write_cell = tr.select_one(".td-write")
        access_cell = tr.select_one(".td-access")

        rows.append(
            NoticeRow(
                source=source.name,
                title=title_cell.get_text(strip=True),
                url=source.detail_url(article_seq),
                author=write_cell.get_text(strip=True) if write_cell else "",
                posted_date=_parse_date(date_cell.get_text(strip=True)).isoformat()
                if date_cell
                else datetime.date.today().isoformat(),
                views=_parse_int(access_cell.get_text(strip=True) if access_cell else None),
                is_pinned="isnotice" in (tr.get("class") or []),
            )
        )
    return rows


def fetch_cms_board_page(source: CmsBoardSource, page: int) -> list[NoticeRow]:
    response = requests.get(
        source.list_url,
        params={"mCode": source.m_code, "mgr_seq": source.mgr_seq, "page": page},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    rows: list[NoticeRow] = []
    for tr in soup.select("table.board-list-table tbody tr"):
        link = tr.select_one(".subject a")
        if link is None:
            continue
        href = link.get("href", "")
        match = re.search(r"board_seq=(\d+)", href)
        board_seq = match.group(1) if match else ""
        date_cell = tr.select_one(".date")
        writer_cell = tr.select_one(".writer")
        cnt_cell = tr.select_one(".cnt")

        rows.append(
            NoticeRow(
                source=source.name,
                title=link.get_text(strip=True),
                url=source.detail_url(board_seq),
                author=writer_cell.get_text(strip=True) if writer_cell else "",
                posted_date=_parse_date(date_cell.get_text(strip=True)).isoformat()
                if date_cell
                else datetime.date.today().isoformat(),
                views=_parse_int(cnt_cell.get_text(strip=True) if cnt_cell else None),
                is_pinned="isnotice" in (tr.get("class") or []),
            )
        )
    return rows


def crawl_artcl_view_source(
    source: ArtclViewSource, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> list[NoticeRow]:
    cutoff = datetime.date.today() - datetime.timedelta(days=lookback_days)
    collected: list[NoticeRow] = []

    for page in range(1, MAX_PAGES + 1):
        rows = fetch_artcl_view_page(source, page)
        if not rows:
            break

        if page == 1:
            collected.extend(row for row in rows if row.is_pinned)

        non_pinned = [row for row in rows if not row.is_pinned]
        collected.extend(
            row for row in non_pinned if datetime.date.fromisoformat(row.posted_date) >= cutoff
        )
        if non_pinned and all(
            datetime.date.fromisoformat(row.posted_date) < cutoff for row in non_pinned
        ):
            break

    return collected


def crawl_cms_board_source(
    source: CmsBoardSource, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> list[NoticeRow]:
    cutoff = datetime.date.today() - datetime.timedelta(days=lookback_days)
    collected: list[NoticeRow] = []

    for page in range(1, MAX_PAGES + 1):
        rows = fetch_cms_board_page(source, page)
        if not rows:
            break

        if page == 1:
            collected.extend(row for row in rows if row.is_pinned)

        non_pinned = [row for row in rows if not row.is_pinned]
        collected.extend(
            row for row in non_pinned if datetime.date.fromisoformat(row.posted_date) >= cutoff
        )
        if non_pinned and all(
            datetime.date.fromisoformat(row.posted_date) < cutoff for row in non_pinned
        ):
            break

    return collected


def fetch_lib_pyxis_page(
    source: LibPyxisSource, offset: int, page_size: int = 20
) -> list[NoticeRow]:
    response = requests.get(
        source.bulletins_api_url,
        params={
            "nameOption": "",
            "dateCreated": "true",
            "onlyWriter": "false",
            "max": page_size,
            "offset": offset,
        },
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    items = response.json().get("data", {}).get("list", [])

    rows: list[NoticeRow] = []
    for item in items:
        posted = item.get("dateCreated") or ""
        posted_date = posted.split(" ")[0] if posted else datetime.date.today().isoformat()
        rows.append(
            NoticeRow(
                source=source.name,
                title=item.get("title", ""),
                url=source.detail_url(str(item.get("id", ""))),
                author=item.get("writer") or "",
                posted_date=posted_date,
                views=item.get("hitCnt"),
                is_pinned=False,
            )
        )
    return rows


def crawl_lib_pyxis_source(
    source: LibPyxisSource, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> list[NoticeRow]:
    cutoff = datetime.date.today() - datetime.timedelta(days=lookback_days)
    collected: list[NoticeRow] = []
    page_size = 20

    for page in range(MAX_PAGES):
        rows = fetch_lib_pyxis_page(source, offset=page * page_size, page_size=page_size)
        if not rows:
            break
        collected.extend(
            row for row in rows if datetime.date.fromisoformat(row.posted_date) >= cutoff
        )
        if all(datetime.date.fromisoformat(row.posted_date) < cutoff for row in rows):
            break

    return collected


def fetch_job_board_page(source: JobBoardSource, page: int) -> list[NoticeRow]:
    response = requests.get(
        source.list_url(page), headers={"User-Agent": USER_AGENT}, timeout=30
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    rows: list[NoticeRow] = []
    for li in soup.select("li.tbody"):
        link = li.select_one(".title a")
        if link is None:
            continue
        title = link.get_text(strip=True)
        if not title:
            # 텍스트 없이 이미지 배너만 있는 공지 (예: job 204025) - 제목을 알 수 없어 제외
            continue
        href = link.get("href", "")
        match = re.search(r"/view/(\d+)", href)
        article_id = match.group(1) if match else ""
        time_cell = li.select_one(".reg_date time")
        hit_cell = li.select_one(".hit")

        rows.append(
            NoticeRow(
                source=source.name,
                title=title,
                url=source.detail_url(article_id),
                author="",
                posted_date=(time_cell.get("datetime", "") or "")[:10]
                if time_cell
                else datetime.date.today().isoformat(),
                views=_parse_int(hit_cell.get_text(strip=True) if hit_cell else None),
                is_pinned="notice" in (li.get("class") or []),
            )
        )
    return rows


def crawl_job_board_source(
    source: JobBoardSource, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> list[NoticeRow]:
    cutoff = datetime.date.today() - datetime.timedelta(days=lookback_days)
    collected: list[NoticeRow] = []

    for page in range(1, MAX_PAGES + 1):
        rows = fetch_job_board_page(source, page)
        if not rows:
            break

        if page == 1:
            collected.extend(row for row in rows if row.is_pinned)

        non_pinned = [row for row in rows if not row.is_pinned]
        collected.extend(
            row for row in non_pinned if datetime.date.fromisoformat(row.posted_date) >= cutoff
        )
        if non_pinned and all(
            datetime.date.fromisoformat(row.posted_date) < cutoff for row in non_pinned
        ):
            break

    return collected


def crawl_all_notice_boards(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> list[NoticeRow]:
    results: list[NoticeRow] = []
    for source in ARTCL_VIEW_SOURCES:
        results.extend(crawl_artcl_view_source(source, lookback_days))
    for source in CMS_BOARD_SOURCES:
        results.extend(crawl_cms_board_source(source, lookback_days))
    for source in LIB_PYXIS_SOURCES:
        results.extend(crawl_lib_pyxis_source(source, lookback_days))
    for source in JOB_BOARD_SOURCES:
        results.extend(crawl_job_board_source(source, lookback_days))
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl PNU public notice boards")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("raw_data/crawled_data/notice_boards"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = crawl_all_notice_boards(lookback_days=args.lookback_days)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{datetime.date.today().isoformat()}.json"
    output_path.write_text(
        json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    counts_by_source: dict[str, int] = {}
    for row in rows:
        counts_by_source[row.source] = counts_by_source.get(row.source, 0) + 1

    print(
        json.dumps(
            {
                "lookback_days": args.lookback_days,
                "total_count": len(rows),
                "counts_by_source": counts_by_source,
                "output_path": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


PNU_COLLEGES_URL = "https://www.pusan.ac.kr/kor/CMS/Contents/Contents.do?mCode=MN003"
USER_AGENT = "PlanU curriculum source discovery/0.1 (+https://github.com/PNU-2026-AI-Hackathon)"
REQUEST_TIMEOUT = (4, 6)
DOWNLOAD_EXTENSIONS = {
    ".pdf",
    ".hwp",
    ".hwpx",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
PAGE_EXTENSIONS = {"", ".html", ".htm", ".do", ".jsp", ".php", ".asp", ".aspx"}
CURRICULUM_KEYWORDS = [
    "교육과정",
    "교과과정",
    "학부교육과정",
    "졸업",
    "졸업요건",
    "이수",
    "교과목",
    "전공",
    "복수전공",
    "부전공",
    "심화전공",
    "연계전공",
    "curriculum",
    "undergraduate",
    "graduation",
    "major",
    "minor",
]
UNDERGRAD_KEYWORDS = ["학부", "학부교육과정", "학사", "undergraduate"]
MINOR_KEYWORDS = ["부전공", "minor"]
DUAL_MAJOR_KEYWORDS = ["복수전공", "복수", "다중전공", "다중", "dual", "double", "multiple"]
NEGATIVE_KEYWORDS = [
    "대학원",
    "graduate",
    "석사",
    "박사",
    "교수",
    "뉴스",
    "공지",
    "갤러리",
    "취업",
    "입학",
    "행사",
]


@dataclass(frozen=True)
class TargetProgram:
    college_name: str
    academic_program_code: str
    program_name: str
    folder_path: str


@dataclass(frozen=True)
class HomepageLink:
    college_name: str
    listed_program_name: str
    homepage_url: str
    pnu_college_page_url: str


@dataclass(frozen=True)
class SourceCandidate:
    college_name: str
    academic_program_code: str
    program_name: str
    homepage_url: str
    candidate_url: str
    candidate_title: str
    candidate_kind: str
    file_ext: str
    score: int
    has_curriculum_keyword: bool
    has_undergraduate_keyword: bool
    has_minor_keyword: bool
    has_dual_major_keyword: bool
    source_page_url: str
    downloaded_path: str = ""


def load_targets(path: Path) -> list[TargetProgram]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    return [
        TargetProgram(
            college_name=row["college_name"],
            academic_program_code=row["academic_program_code"],
            program_name=row["program_name"],
            folder_path=row["folder_path"],
        )
        for row in rows
    ]


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def discover_pnu_homepages(
    session: requests.Session,
    start_url: str = PNU_COLLEGES_URL,
    delay_seconds: float = 0.0,
) -> list[HomepageLink]:
    start_html = fetch_text(session, start_url)
    start_soup = BeautifulSoup(start_html, "html.parser")
    college_pages = _college_pages(start_soup, start_url)

    links: dict[tuple[str, str, str], HomepageLink] = {}
    for college_name, college_url in college_pages:
        html = fetch_text(session, college_url)
        soup = BeautifulSoup(html, "html.parser")
        page_college_name = _page_college_name(soup) or college_name
        for name, href in _department_homepage_links(soup, college_url):
            key = (page_college_name, normalize_name(name), href)
            links[key] = HomepageLink(
                college_name=page_college_name,
                listed_program_name=clean_text(name),
                homepage_url=href,
                pnu_college_page_url=college_url,
            )
        if delay_seconds:
            time.sleep(delay_seconds)
    return sorted(links.values(), key=lambda item: (item.college_name, item.listed_program_name, item.homepage_url))


def discover_source_candidates(
    session: requests.Session,
    target: TargetProgram,
    homepage_url: str,
    max_pages: int = 40,
    delay_seconds: float = 0.0,
) -> list[SourceCandidate]:
    if not homepage_url:
        return []

    origin = origin_for(homepage_url)
    queue = [homepage_url]
    seen = set()
    candidates: dict[str, SourceCandidate] = {}

    while queue and len(seen) < max_pages:
        page_url = queue.pop(0)
        page_url = normalize_url(page_url)
        if page_url in seen or not same_origin(origin, page_url):
            continue
        seen.add(page_url)

        try:
            final_page_url, html = fetch_page(session, page_url)
        except requests.RequestException:
            continue

        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        page_score = score_text(final_page_url, soup.title.get_text(" ", strip=True) if soup.title else "", page_text[:1000])
        if page_score >= 8:
            candidate = make_candidate(
                target,
                homepage_url,
                final_page_url,
                soup.title.get_text(" ", strip=True) if soup.title else "",
                final_page_url,
                page_score,
            )
            candidates[candidate.candidate_url] = candidate

        for anchor in soup.find_all("a", href=True):
            href = normalize_url(urljoin(final_page_url, anchor["href"]))
            if not href or href.startswith("mailto:") or href.startswith("tel:"):
                continue

            title = clean_text(anchor.get_text(" ", strip=True)) or href.rsplit("/", 1)[-1]
            score = score_text(href, title, "")
            ext = file_extension(href, title)
            if score > 0:
                candidate = make_candidate(target, homepage_url, href, title, final_page_url, score)
                existing = candidates.get(candidate.candidate_url)
                if existing is None or candidate.score > existing.score:
                    candidates[candidate.candidate_url] = candidate

            if should_follow(href, origin, title, score, ext) and href not in seen and href not in queue:
                queue.append(href)

        if delay_seconds:
            time.sleep(delay_seconds)

    return sorted(candidates.values(), key=lambda item: (-item.score, item.candidate_url))


def download_candidates(
    session: requests.Session,
    candidates: Iterable[SourceCandidate],
    target: TargetProgram,
    root: Path,
    max_downloads: int = 12,
) -> list[SourceCandidate]:
    output_dir = root / target.college_name / f"{target.academic_program_code}__{target.program_name}" / "00_sources_discovered"
    output_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for candidate in list(candidates)[:max_downloads]:
        ext = candidate.file_ext or ".html"
        if ext not in DOWNLOAD_EXTENSIONS and candidate.candidate_kind != "page":
            continue
        if candidate.score < 6:
            continue
        try:
            response = session.get(candidate.candidate_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException:
            downloaded.append(candidate)
            continue

        content_type = response.headers.get("content-type", "")
        filename_ext = ext
        if candidate.candidate_kind == "page":
            filename_ext = ".html"
        elif filename_ext == "":
            filename_ext = mimetypes.guess_extension(content_type.split(";", 1)[0]) or ".bin"
        filename = safe_filename(candidate.candidate_title or candidate.candidate_url, filename_ext)
        path = output_dir / filename
        if path.exists():
            digest = hashlib.sha1(candidate.candidate_url.encode()).hexdigest()[:8]
            path = output_dir / f"{path.stem}_{digest}{path.suffix}"
        path.write_bytes(response.content)
        downloaded.append(
            SourceCandidate(
                **{
                    **candidate.__dict__,
                    "downloaded_path": str(path),
                }
            )
        )
    return downloaded


def match_homepages(
    targets: list[TargetProgram],
    homepages: list[HomepageLink],
) -> list[dict[str, str]]:
    by_college_name = {}
    by_name = {}
    for homepage in homepages:
        for variant in normalized_name_variants(homepage.listed_program_name):
            by_college_name[(homepage.college_name, variant)] = homepage
            by_name.setdefault(variant, []).append(homepage)

    rows = []
    for target in targets:
        target_variants = normalized_name_variants(target.program_name)
        homepage = first_variant_match(
            target_variants,
            lambda variant: by_college_name.get((target.college_name, variant)),
        )
        method = "college_name_variant"
        status = "matched"
        if homepage is None:
            matches = first_variant_matches(target_variants, by_name)
            if len(matches) == 1:
                homepage = matches[0]
                method = "name_variant"
            elif len(matches) > 1:
                homepage = matches[0]
                method = "name_variant_ambiguous"
                status = "ambiguous"
            else:
                homepage = fuzzy_homepage(target, homepages)
                method = "fuzzy"
                status = "matched" if homepage else "unmatched"
        rows.append(
            {
                "college_name": target.college_name,
                "academic_program_code": target.academic_program_code,
                "program_name": target.program_name,
                "listed_college_name": homepage.college_name if homepage else "",
                "listed_program_name": homepage.listed_program_name if homepage else "",
                "homepage_url": homepage.homepage_url if homepage else "",
                "pnu_college_page_url": homepage.pnu_college_page_url if homepage else "",
                "match_status": status,
                "match_method": method if homepage else "",
            }
        )
    return rows


def review_rows(
    targets: list[TargetProgram],
    homepage_rows: list[dict[str, str]],
    candidates: list[SourceCandidate],
) -> list[dict[str, str]]:
    candidate_map: dict[str, list[SourceCandidate]] = {}
    for candidate in candidates:
        candidate_map.setdefault(candidate.academic_program_code, []).append(candidate)

    homepage_map = {row["academic_program_code"]: row for row in homepage_rows}
    rows = []
    for target in targets:
        homepage = homepage_map.get(target.academic_program_code, {})
        target_candidates = candidate_map.get(target.academic_program_code, [])
        undergraduate = [item for item in target_candidates if item.has_undergraduate_keyword or item.score >= 10]
        minor = [item for item in target_candidates if item.has_minor_keyword]
        dual = [item for item in target_candidates if item.has_dual_major_keyword]
        downloads = [
            item
            for item in target_candidates
            if item.candidate_kind == "file" or item.file_ext in DOWNLOAD_EXTENSIONS or item.downloaded_path
        ]
        reasons = []
        if not homepage.get("homepage_url"):
            reasons.append("department homepage not found on PNU college pages")
        if not target_candidates:
            reasons.append("no curriculum-related candidate found")
        if not undergraduate:
            reasons.append("no clear undergraduate curriculum candidate")
        if not minor:
            reasons.append("no minor candidate")
        if not dual:
            reasons.append("no dual-major candidate")
        rows.append(
            {
                "college_name": target.college_name,
                "academic_program_code": target.academic_program_code,
                "program_name": target.program_name,
                "homepage_url": homepage.get("homepage_url", ""),
                "homepage_match_status": homepage.get("match_status", "unmatched"),
                "candidate_count": str(len(target_candidates)),
                "undergraduate_candidate_count": str(len(undergraduate)),
                "minor_candidate_count": str(len(minor)),
                "dual_major_candidate_count": str(len(dual)),
                "downloadable_candidate_count": str(len(downloads)),
                "needs_review": "Y" if reasons else "N",
                "review_reason": "; ".join(reasons),
            }
        )
    return rows


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_text(session: requests.Session, url: str) -> str:
    return fetch_page(session, url)[1]


def fetch_page(session: requests.Session, url: str) -> tuple[str, str]:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    if response.apparent_encoding:
        response.encoding = response.apparent_encoding
    text = response.text
    refresh_url = cms_site_url(session, response.url, text) or meta_refresh_url(text, response.url)
    if refresh_url and normalize_url(refresh_url) != normalize_url(response.url):
        response = session.get(refresh_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        if response.apparent_encoding:
            response.encoding = response.apparent_encoding
        text = response.text
    return response.url, text


def cms_site_url(session: requests.Session, base_url: str, html: str) -> str:
    if "pnuDomainChk.do" not in html:
        return ""
    endpoint = urljoin(base_url, "/his/pnuDomainChk.do")
    try:
        response = session.post(endpoint, timeout=REQUEST_TIMEOUT, headers={"Referer": base_url})
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return ""
    site_url = data.get("siteUrl", "")
    if site_url and site_url != "nonononono":
        return site_url
    return ""


def meta_refresh_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta"):
        http_equiv = (meta.get("http-equiv") or "").lower()
        content = meta.get("content") or ""
        if http_equiv == "refresh" and "url=" in content.lower():
            match = re.search(r"url\s*=\s*([^;]+)", content, flags=re.IGNORECASE)
            if match:
                return urljoin(base_url, match.group(1).strip("'\" "))
    return ""


def _college_pages(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    pages = []
    for anchor in soup.find_all("a", href=True):
        name = clean_text(anchor.get_text(" ", strip=True))
        if not name.endswith("대학") and name != "학부대학":
            continue
        href = normalize_url(urljoin(base_url, anchor["href"]))
        if "Contents.do" not in href or "mCode=" not in href:
            continue
        if (name, href) not in pages:
            pages.append((name, href))
    return pages


def _department_homepage_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    links = []
    for anchor in soup.find_all("a", href=True):
        name = clean_text(anchor.get_text(" ", strip=True))
        href = normalize_url(urljoin(base_url, anchor["href"]))
        host = urlparse(href).netloc
        if not name or not host.endswith("pusan.ac.kr"):
            continue
        if "홈페이지바로가기" in name or name.endswith("대학"):
            continue
        if "Contents.do" in href:
            continue
        if len(name) > 40:
            continue
        if any(token in name for token in ["본부", "기관", "연구소", "센터", "병원", "총학생회"]):
            continue
        if any(token in name for token in ["학과", "학부", "전공", "의예과", "의학과", "약학", "교육과", "School", "Program"]):
            links.append((name, href))
    return links


def _page_college_name(soup: BeautifulSoup) -> str:
    heading = soup.find(["h3", "h2"])
    return clean_text(heading.get_text(" ", strip=True)) if heading else ""


def make_candidate(
    target: TargetProgram,
    homepage_url: str,
    candidate_url: str,
    title: str,
    source_page_url: str,
    score: int,
) -> SourceCandidate:
    ext = file_extension(candidate_url, title)
    text = " ".join([candidate_url, title])
    return SourceCandidate(
        college_name=target.college_name,
        academic_program_code=target.academic_program_code,
        program_name=target.program_name,
        homepage_url=homepage_url,
        candidate_url=candidate_url,
        candidate_title=clean_text(title),
        candidate_kind="file" if is_download_url(candidate_url) or ext in DOWNLOAD_EXTENSIONS else "page",
        file_ext=ext,
        score=score,
        has_curriculum_keyword=has_any(text, CURRICULUM_KEYWORDS),
        has_undergraduate_keyword=has_any(text, UNDERGRAD_KEYWORDS),
        has_minor_keyword=has_any(text, MINOR_KEYWORDS),
        has_dual_major_keyword=has_any(text, DUAL_MAJOR_KEYWORDS),
        source_page_url=source_page_url,
    )


def score_text(url: str, title: str, body: str) -> int:
    text = normalize_for_score(" ".join([url, title, body]))
    score = 0
    for keyword in CURRICULUM_KEYWORDS:
        if normalize_for_score(keyword) in text:
            score += 4
    for keyword in UNDERGRAD_KEYWORDS:
        if normalize_for_score(keyword) in text:
            score += 2
    for keyword in MINOR_KEYWORDS + DUAL_MAJOR_KEYWORDS:
        if normalize_for_score(keyword) in text:
            score += 3
    for keyword in NEGATIVE_KEYWORDS:
        if normalize_for_score(keyword) in text:
            score -= 2
    if is_download_url(url) or file_extension(url, title) in DOWNLOAD_EXTENSIONS:
        score += 3
    return max(score, 0)


def should_follow(url: str, origin: str, title: str, score: int, ext: str) -> bool:
    if not same_origin(origin, url):
        return False
    if ext not in PAGE_EXTENSIONS:
        return False
    if score > 0:
        return True
    text = normalize_for_score(" ".join([url, title]))
    return any(normalize_for_score(keyword) in text for keyword in ["학사", "교육", "졸업", "전공", "curriculum"])


def fuzzy_homepage(target: TargetProgram, homepages: list[HomepageLink]) -> HomepageLink | None:
    target_name = normalize_name(target.program_name)
    best = None
    best_score = 0
    for homepage in homepages:
        name = normalize_name(homepage.listed_program_name)
        if target_name in name or name in target_name:
            score = min(len(target_name), len(name))
            if homepage.college_name == target.college_name:
                score += 10
            if score > best_score:
                best = homepage
                best_score = score
    return best if best_score >= 6 else None


def normalize_url(url: str) -> str:
    return urldefrag(url.strip())[0]


def origin_for(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def same_origin(origin: str, url: str) -> bool:
    return urlparse(origin).netloc == urlparse(url).netloc


def file_extension(url: str, title: str = "") -> str:
    path = urlparse(url).path.lower()
    match = re.search(r"(\.[a-z0-9]+)$", path)
    path_ext = match.group(1) if match else ""
    title_match = re.search(r"(\.[a-z0-9]+)(?:\s|$)", title.lower())
    title_ext = title_match.group(1) if title_match else ""
    if title_ext and (path_ext in {"", ".do"} or "download.do" in path):
        return title_ext
    return path_ext or title_ext


def is_download_url(url: str) -> bool:
    return "download.do" in urlparse(url).path.lower()


def safe_filename(title: str, ext: str) -> str:
    title = re.sub(r"[\\/:*?\"<>|]+", "_", clean_text(title))
    title = re.sub(r"\s+", "_", title).strip("_")[:90] or "source"
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{title}{ext}"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_name(value: str) -> str:
    return re.sub(r"[\s:()（）·ㆍ・.]", "", value or "").lower()


def normalized_name_variants(value: str) -> list[str]:
    raw = clean_text(value)
    variants = [
        raw,
        re.sub(r"\([^)]*\)", "", raw),
        re.sub(r"（[^）]*）", "", raw),
    ]
    if raw.endswith("(통합6년제)"):
        variants.append(raw.replace("(통합6년제)", ""))
    normalized = []
    seen = set()
    for variant in variants:
        key = normalize_name(variant)
        if key and key not in seen:
            seen.add(key)
            normalized.append(key)
    return normalized


def first_variant_match(variants: list[str], lookup: Callable[[str], HomepageLink | None]) -> HomepageLink | None:
    for variant in variants:
        match = lookup(variant)
        if match:
            return match
    return None


def first_variant_matches(
    variants: list[str],
    by_name: dict[str, list[HomepageLink]],
) -> list[HomepageLink]:
    seen = set()
    matches = []
    for variant in variants:
        for homepage in by_name.get(variant, []):
            key = (homepage.college_name, homepage.listed_program_name, homepage.homepage_url)
            if key not in seen:
                seen.add(key)
                matches.append(homepage)
        if matches:
            return matches
    return matches


def normalize_for_score(value: str) -> str:
    return re.sub(r"[-\s_\\:()（）·ㆍ・.]", "", value or "").lower()


def has_any(value: str, keywords: list[str]) -> bool:
    normalized = normalize_for_score(value)
    return any(normalize_for_score(keyword) in normalized for keyword in keywords)

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parent))

from build_department_curriculum_courses import (  # noqa: E402
    CourseCatalogIndex,
    empty_match,
    match_course,
    read_course_catalog,
)


# 실제 수강편람 과목코드는 항상 대문자 2~3자 + 숫자 7자리(9~10자)이며 소문자를 포함하지 않는다.
# (이전에는 "Z[A-Z]z?\d{6}" 같은 변형도 코드로 인식했는데, 이는 "효원균형" 교양영역
# 표에 나오는 ZFz000091 같은 placeholder 라벨까지 과목코드로 잘못 캡처하는 버그였다.)
COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,3}\d{7}\b")
SOURCE_SUFFIXES = {
    ".html",
    ".htm",
    ".txt",
    ".pdf",
    ".hwp",
    ".hwpx",
    ".xls",
    ".xlsx",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
COURSE_NAME_STOPLIST = {
    "교육과정",
    "교과과정",
    "졸업요건",
    "부전공",
    "복수전공",
    "심화전공",
    "연계전공",
    "학부",
    "대학원",
}

COURSE_COLUMNS = [
    "candidate_id",
    "college",
    "department_code",
    "department_name",
    "program_type",
    "requirement_category",
    "curriculum_year",
    "recommended_year",
    "recommended_semester",
    "raw_course_code",
    "raw_course_name",
    "raw_credit",
    "source_type",
    "source_file",
    "source_title",
    "source_url",
    "extraction_method",
    "context",
    "matched_course_code",
    "matched_course_name",
    "match_status",
    "match_method",
    "matched_terms",
    "matched_departments",
    "needs_review",
    "review_reason",
]

TEXT_RULE_COLUMNS = [
    "rule_id",
    "college",
    "department_code",
    "department_name",
    "program_type",
    "requirement_category",
    "source_type",
    "source_file",
    "source_title",
    "source_url",
    "raw_text",
    "needs_review",
    "review_reason",
]

SOURCE_STATUS_COLUMNS = [
    "college",
    "department_code",
    "department_name",
    "source_type",
    "source_file",
    "source_title",
    "source_url",
    "extraction_status",
    "extraction_method",
    "text_length",
    "table_count",
    "course_candidate_count",
    "rule_candidate_count",
    "error",
]


@dataclass(frozen=True)
class DepartmentTarget:
    college: str
    department_code: str
    department_name: str
    folder_path: Path


@dataclass
class SourceDoc:
    source_type: str
    path: Path
    title: str
    url: str
    text: str
    tables: list[list[list[str]]]
    extraction_status: str
    extraction_method: str
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract structured curriculum candidates from downloaded HTML/PDF/HWP/image/etc sources."
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path(
            "../raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv"
        ),
    )
    parser.add_argument(
        "--downloads",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_source_discovery/downloaded_curriculum_sources.csv"),
    )
    parser.add_argument(
        "--course-catalog",
        type=Path,
        default=Path(
            "../raw_data/parsed_experiments/course_catalog_multi_term/2023_2026_course_catalog_combined_cleaned_dedup.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_structured_candidates"),
    )
    parser.add_argument("--max-name-matches-per-context", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = read_targets(args.targets.resolve())
    downloads_by_code = group_by_code(read_csv(args.downloads.resolve()), "academic_program_code")
    catalog_index = read_course_catalog(args.course_catalog.resolve())
    catalog_lookup = build_catalog_name_lookup(catalog_index)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    all_course_rows: list[dict[str, str]] = []
    all_rule_rows: list[dict[str, str]] = []
    all_status_rows: list[dict[str, str]] = []
    source_type_counts: Counter[str] = Counter()
    extraction_status_counts: Counter[str] = Counter()

    course_counter = 0
    rule_counter = 0

    for target in targets:
        docs = load_source_docs(target, downloads_by_code.get(target.department_code, []))
        dept_course_rows: list[dict[str, str]] = []
        dept_rule_rows: list[dict[str, str]] = []
        dept_status_rows: list[dict[str, str]] = []

        for doc in docs:
            source_type_counts[doc.source_type] += 1
            extraction_status_counts[doc.extraction_status] += 1
            course_rows = extract_course_candidates(
                target=target,
                doc=doc,
                catalog_index=catalog_index,
                catalog_lookup=catalog_lookup,
                max_name_matches_per_context=args.max_name_matches_per_context,
            )
            rule_rows = extract_text_rule_candidates(target, doc)

            for row in course_rows:
                course_counter += 1
                row["candidate_id"] = f"coursecand_{course_counter:06d}"
            for row in rule_rows:
                rule_counter += 1
                row["rule_id"] = f"rulecand_{rule_counter:06d}"

            status_row = {
                "college": target.college,
                "department_code": target.department_code,
                "department_name": target.department_name,
                "source_type": doc.source_type,
                "source_file": display_path(doc.path),
                "source_title": doc.title,
                "source_url": doc.url,
                "extraction_status": doc.extraction_status,
                "extraction_method": doc.extraction_method,
                "text_length": str(len(doc.text)),
                "table_count": str(len(doc.tables)),
                "course_candidate_count": str(len(course_rows)),
                "rule_candidate_count": str(len(rule_rows)),
                "error": doc.error,
            }

            dept_course_rows.extend(course_rows)
            dept_rule_rows.extend(rule_rows)
            dept_status_rows.append(status_row)

        write_department_json(target, docs, dept_course_rows, dept_rule_rows, dept_status_rows)
        all_course_rows.extend(dept_course_rows)
        all_rule_rows.extend(dept_rule_rows)
        all_status_rows.extend(dept_status_rows)

    write_csv(output_dir / "curriculum_course_candidates.csv", COURSE_COLUMNS, all_course_rows)
    write_csv(output_dir / "curriculum_text_rule_candidates.csv", TEXT_RULE_COLUMNS, all_rule_rows)
    write_csv(output_dir / "source_extraction_status.csv", SOURCE_STATUS_COLUMNS, all_status_rows)
    write_json(
        output_dir / "summary.json",
        {
            "targets": len(targets),
            "sources": len(all_status_rows),
            "course_candidates": len(all_course_rows),
            "text_rule_candidates": len(all_rule_rows),
            "source_types": dict(source_type_counts),
            "extraction_statuses": dict(extraction_status_counts),
            "outputs": {
                "course_candidates": str(output_dir / "curriculum_course_candidates.csv"),
                "text_rule_candidates": str(output_dir / "curriculum_text_rule_candidates.csv"),
                "source_status": str(output_dir / "source_extraction_status.csv"),
            },
            "per_department_output": "02_rule_candidates/structured_curriculum_candidates.json",
            "notes": [
                "Rows are extraction candidates, not approved graduation requirements.",
                "HWP sources may require external converters; image sources use local macOS Vision OCR when available.",
                "Use matched_course_code and needs_review before loading into DB.",
            ],
        },
    )
    write_readme(output_dir)
    print(output_dir)


def read_targets(path: Path) -> list[DepartmentTarget]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [
            DepartmentTarget(
                college=row["college_name"],
                department_code=row["academic_program_code"],
                department_name=row["program_name"],
                folder_path=Path("..") / row["folder_path"],
            )
            for row in csv.DictReader(file)
        ]


def load_source_docs(target: DepartmentTarget, download_rows: list[dict[str, str]]) -> list[SourceDoc]:
    seen: set[Path] = set()
    docs: list[SourceDoc] = []

    for source_dir_name in ("00_sources", "00_sources_discovered"):
        source_dir = target.folder_path / source_dir_name
        if not source_dir.exists():
            continue
        for path in sorted(source_dir.iterdir()):
            if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in SOURCE_SUFFIXES:
                seen.add(path.resolve())
                docs.append(extract_source_doc(path, title=path.stem, url=""))

    for row in download_rows:
        if row.get("download_status") != "downloaded" or not row.get("downloaded_path"):
            continue
        path = Path(row["downloaded_path"])
        if not path.exists() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        docs.append(extract_source_doc(path, title=row.get("candidate_title", path.stem), url=row.get("candidate_url", "")))

    return docs


def extract_source_doc(path: Path, title: str, url: str) -> SourceDoc:
    suffix = path.suffix.lower()
    source_type = source_type_from_suffix(suffix)
    try:
        if source_type == "html":
            text, tables = extract_html(path)
            return SourceDoc(source_type, path, title, url, text, tables, "extracted", "beautifulsoup")
        if source_type == "text":
            text = path.read_text(encoding="utf-8", errors="replace")
            return SourceDoc(source_type, path, title, url, clean_text(text), [], "extracted", "plain_text")
        if source_type == "pdf":
            text = run_text_command(["pdftotext", str(path), "-"])
            return SourceDoc(source_type, path, title, url, clean_text(text), [], "extracted" if text.strip() else "empty", "pdftotext")
        if source_type == "hwp":
            html_text, html_tables, html_error = extract_hwp_via_hwp5html(path)
            if html_text.strip():
                return SourceDoc(source_type, path, title, url, html_text, html_tables, "extracted", "hwp5html")
            text, method, error = extract_hwp_text(path)
            status = "extracted_partial" if text.strip() else "needs_converter"
            return SourceDoc(
                source_type, path, title, url, clean_text(text), [], status, method,
                error or html_error,
            )
        if source_type == "spreadsheet":
            return SourceDoc(source_type, path, title, url, "", [], "needs_parser", "spreadsheet_parser_missing", "")
        if source_type == "image":
            text, method, error = extract_image_text(path)
            status = "extracted" if text.strip() else "needs_ocr"
            return SourceDoc(source_type, path, title, url, clean_text(text), [], status, method, error)
        return SourceDoc(source_type, path, title, url, "", [], "needs_parser", "unsupported_source_type", "")
    except Exception as exc:  # noqa: BLE001 - per-source status report.
        return SourceDoc(source_type, path, title, url, "", [], "failed", source_type, str(exc))


def extract_html(path: Path) -> tuple[str, list[list[list[str]]]]:
    html = path.read_text(encoding="utf-8", errors="replace")
    return extract_html_content(html)


def extract_html_content(html: str) -> tuple[str, list[list[list[str]]]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    tables = []
    for table in soup.find_all("table"):
        table_rows = []
        for tr in table.find_all("tr"):
            cells = [clean_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
            if any(cells):
                table_rows.append(cells)
        if table_rows:
            tables.append(table_rows)
    return clean_text(soup.get_text(" ", strip=True)), tables


def _venv_executable(name: str) -> str | None:
    candidate = Path(sys.executable).parent / name
    return str(candidate) if candidate.exists() else None


def extract_hwp_via_hwp5html(path: Path) -> tuple[str, list[list[list[str]]], str]:
    """pyhwp의 hwp5html로 변환한다. textutil/strings 폴백보다 표 내용을 훨씬 안정적으로
    뽑아낸다 (HWP5는 압축 바이너리 포맷이라 strings만으로는 본문이 거의 안 나온다)."""
    # shutil.which()는 os.environ["PATH"]만 보는데, 이 스크립트를 venv를 activate하지
    # 않고 `.venv/bin/python scripts/...`로 바로 실행하면 venv의 bin/이 PATH에 없어서
    # pip install pyhwp로 깔린 hwp5html을 못 찾는다. 지금 실행 중인 인터프리터와 같은
    # venv의 bin/도 함께 확인한다.
    hwp5html = shutil.which("hwp5html") or _venv_executable("hwp5html")
    if not hwp5html:
        return "", [], "hwp5html not installed (pip install pyhwp)"
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = subprocess.run(
            [hwp5html, str(path), "--output", tmp_dir],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        index_path = Path(tmp_dir) / "index.xhtml"
        if result.returncode != 0 or not index_path.exists():
            return "", [], clean_text(result.stderr)
        xhtml = index_path.read_text(encoding="utf-8", errors="replace")
        text, tables = extract_html_content(xhtml)
        return text, tables, ""


def extract_hwp_text(path: Path) -> tuple[str, str, str]:
    textutil = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if textutil.returncode == 0 and textutil.stdout.strip():
        return textutil.stdout, "textutil", ""

    strings = subprocess.run(
        ["strings", "-a", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    text = strings.stdout if strings.returncode == 0 else ""
    error = clean_text(textutil.stderr or strings.stderr)
    return text, "strings_fallback", error


def extract_image_text(path: Path) -> tuple[str, str, str]:
    swift = shutil.which("swift")
    helper = Path(__file__).resolve().with_name("ocr_image_macos_vision.swift")
    if not swift or not helper.exists():
        return "", "ocr_missing", "macOS Vision OCR helper or swift is not available"

    env = dict(os.environ)
    env.setdefault(
        "CLANG_MODULE_CACHE_PATH",
        str(Path(__file__).resolve().parents[1] / ".swift-module-cache"),
    )
    result = subprocess.run(
        [swift, str(helper), str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    if result.returncode != 0:
        return "", "macos_vision_ocr", clean_text(result.stderr)
    return result.stdout, "macos_vision_ocr", ""


def run_text_command(command: list[str]) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(clean_text(result.stderr))
    return result.stdout


def extract_course_candidates(
    *,
    target: DepartmentTarget,
    doc: SourceDoc,
    catalog_index: CourseCatalogIndex,
    catalog_lookup: dict[str, list[tuple[str, str]]],
    max_name_matches_per_context: int,
) -> list[dict[str, str]]:
    contexts = context_units(doc)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    legend = parse_legend(doc.text)
    symbol_types = legend_symbol_program_types(legend)

    def emit(program_type: str, category: str, code: str, raw_name: str, matched: dict[str, str], review_reason: str) -> None:
        key = (display_path(doc.path), code, raw_name, context[:120], program_type)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            course_row(
                target,
                doc,
                program_type,
                category,
                curriculum_year,
                year_level,
                semester,
                raw_course_code=code,
                raw_course_name=raw_name,
                raw_credit=infer_credit(context),
                matched=matched,
                context=context,
                review_reason=review_reason,
            )
        )

    for context in contexts:
        if not likely_curriculum_context(context):
            continue
        category = infer_requirement_category(context, doc.title)
        program_type = infer_program_type(context, doc.title)
        year_level, semester = infer_recommended_period(context)
        curriculum_year = infer_year(" ".join([doc.title, context]))
        # 범례 기호로 잡힌 복수전공/부전공 필수과목은 원래 분류(전공선택 등)와 무관하게
        # 그 프로그램의 전공필수로 취급한다 (♤/◎ 표시 자체가 "이 과목은 필수"라는 뜻).
        marker_types = marker_program_types(context, symbol_types) if symbol_types else set()

        codes = COURSE_CODE_RE.findall(context)
        for code in codes:
            matched = match_course("", None, target.department_name, catalog_index, code)
            raw_name = matched["course_name"].split("|", 1)[0] if matched["course_name"] else code
            emit(program_type, category, code, raw_name, matched, "candidate extracted from source text by course code")
            for marker_type in marker_types:
                marker_cat = category_for_program(marker_type, "전공필수")
                emit(
                    marker_type, marker_cat, code, raw_name, matched,
                    f"범례 기호로 표시된 {marker_cat} 후보 (candidate extracted from legend marker)",
                )

        for raw_name in find_course_names(context, catalog_lookup, max_name_matches_per_context):
            matched = match_course(raw_name, infer_credit(context), target.department_name, catalog_index)
            review_reasons = ["candidate extracted from source text by course name"]
            if matched["match_status"] != "matched":
                review_reasons.append(f"course catalog match status is {matched['match_status']}")
            emit(program_type, category, "", raw_name, matched, " | ".join(review_reasons))
            for marker_type in marker_types:
                marker_cat = category_for_program(marker_type, "전공필수")
                emit(
                    marker_type, marker_cat, "", raw_name, matched,
                    f"범례 기호로 표시된 {marker_cat} 후보 (candidate extracted from legend marker)",
                )
    return rows


def context_units(doc: SourceDoc) -> list[str]:
    units: list[str] = []
    for table in doc.tables:
        for row in table:
            text = clean_text(" | ".join(row))
            if text:
                units.append(text)
    for line in re.split(r"[\n\r]+|(?<=다\.)\s+", doc.text):
        line = clean_text(line)
        if 8 <= len(line) <= 1200:
            units.append(line)
    return units


def find_course_names(
    context: str,
    catalog_lookup: dict[str, list[tuple[str, str]]],
    limit: int,
) -> list[str]:
    normalized = normalize_for_match(context)
    found: list[tuple[int, str]] = []
    checked = set()
    for char in set(normalized):
        for norm_name, display_name in catalog_lookup.get(char, []):
            if norm_name in checked:
                continue
            checked.add(norm_name)
            if display_name in COURSE_NAME_STOPLIST or norm_name in {normalize_for_match(item) for item in COURSE_NAME_STOPLIST}:
                continue
            if norm_name and norm_name in normalized:
                if name_occurrence_looks_like_program_name(normalized, norm_name):
                    continue
                found.append((len(norm_name), display_name))
    found.sort(reverse=True)
    result = []
    seen = set()
    for _, name in found:
        if name not in seen:
            seen.add(name)
            result.append(name)
        if len(result) >= limit:
            break
    return result


def name_occurrence_looks_like_program_name(normalized_context: str, normalized_name: str) -> bool:
    start = normalized_context.find(normalized_name)
    while start >= 0:
        after = normalized_context[start + len(normalized_name): start + len(normalized_name) + 4]
        before = normalized_context[max(0, start - 4): start]
        if after.startswith("전공") or after.startswith("학과") or after.startswith("학부"):
            return True
        if before.endswith("정보컴퓨터공학부") or before.endswith("학부"):
            return True
        start = normalized_context.find(normalized_name, start + 1)
    return False


def extract_text_rule_candidates(target: DepartmentTarget, doc: SourceDoc) -> list[dict[str, str]]:
    rows = []
    seen = set()
    for context in context_units(doc):
        if not likely_rule_context(context):
            continue
        key = (display_path(doc.path), context[:200])
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "rule_id": "",
                "college": target.college,
                "department_code": target.department_code,
                "department_name": target.department_name,
                "program_type": infer_program_type(context, doc.title),
                "requirement_category": infer_requirement_category(context, doc.title),
                "source_type": doc.source_type,
                "source_file": display_path(doc.path),
                "source_title": doc.title,
                "source_url": doc.url,
                "raw_text": context[:2000],
                "needs_review": "Y",
                "review_reason": "raw rule-like text extracted from source; human validation required",
            }
        )
    return rows


def course_row(
    target: DepartmentTarget,
    doc: SourceDoc,
    program_type: str,
    category: str,
    curriculum_year: str,
    year_level: str,
    semester: str,
    raw_course_code: str,
    raw_course_name: str,
    raw_credit: str,
    matched: dict[str, str],
    context: str,
    review_reason: str,
) -> dict[str, str]:
    return {
        "candidate_id": "",
        "college": target.college,
        "department_code": target.department_code,
        "department_name": target.department_name,
        "program_type": program_type,
        "requirement_category": category,
        "curriculum_year": curriculum_year,
        "recommended_year": year_level,
        "recommended_semester": semester,
        "raw_course_code": raw_course_code,
        "raw_course_name": raw_course_name,
        "raw_credit": raw_credit,
        "source_type": doc.source_type,
        "source_file": display_path(doc.path),
        "source_title": doc.title,
        "source_url": doc.url,
        "extraction_method": doc.extraction_method,
        "context": context[:2000],
        "matched_course_code": matched["course_code"],
        "matched_course_name": matched["course_name"],
        "match_status": matched["match_status"],
        "match_method": matched["match_method"],
        "matched_terms": matched["terms"],
        "matched_departments": matched["departments"],
        "needs_review": "Y",
        "review_reason": review_reason,
    }


def likely_curriculum_context(text: str) -> bool:
    compact = normalize_for_match(text)
    if COURSE_CODE_RE.search(text):
        return True
    keywords = [
        "교양필수",
        "교양선택",
        "전공기초",
        "전공필수",
        "전공선택",
        "전필",
        "전선",
        "부전공",
        "복수전공",
        "이수과목",
        "필수과목",
        "교육과정",
        "교과과정",
    ]
    return any(normalize_for_match(keyword) in compact for keyword in keywords)


def likely_rule_context(text: str) -> bool:
    compact = normalize_for_match(text)
    keywords = [
        "졸업요건",
        "졸업인증",
        "부전공",
        "복수전공",
        "필수이수",
        "이수학점",
        "필수과목",
        "선발기준",
        "신청방법",
        "신청서",
        "성적증명서",
        "영어",
        "논문",
        "인증",
        "학점이상",
    ]
    return any(normalize_for_match(keyword) in compact for keyword in keywords)


def infer_requirement_category(context: str, title: str = "") -> str:
    text = normalize_for_match(" ".join([title, context]))
    program = infer_program_type(context, title)
    if "교양필수" in text or "교양 필수" in context:
        return "교양필수"
    if "교양선택" in text or "교양 선택" in context:
        return "교양선택"
    if "기초교양" in text or "기초 교양" in context:
        return "기초교양"
    if "전공기초" in text or "전공 기초" in context or "전기" in text:
        return category_for_program(program, "전공기초")
    if "전공필수" in text or "전공 필수" in context or "전필" in text or "필수과목" in text:
        return category_for_program(program, "전공필수")
    if "전공선택" in text or "전공 선택" in context or "전선" in text:
        return category_for_program(program, "전공선택")
    if "일반선택" in text or "일선" in text:
        return "일반선택"
    if "졸업요건" in text or "졸업인증" in text:
        return "졸업요건"
    if program == "minor":
        return "부전공요건"
    if program == "dual_major":
        return "복수전공요건"
    return "unknown"


def category_for_program(program_type: str, base: str) -> str:
    if program_type == "minor":
        return base.replace("전공", "부전공", 1)
    if program_type == "dual_major":
        return base.replace("전공", "복수전공", 1)
    return base


def infer_program_type(context: str, title: str = "") -> str:
    text = normalize_for_match(" ".join([title, context]))
    if "복수전공" in text or "다중전공" in text:
        return "dual_major"
    if "부전공" in text:
        return "minor"
    if "심화전공" in text:
        return "advanced_major"
    return "major"


# 부산대 학과 교육과정표는 "◎ 부전공 필수과목, ♤ 최소전공(복수전공) 필수 과목"처럼
# 과목명 앞에 기호를 붙이고 문서 상단 범례에서 기호를 정의하는 경우가 많다. 학과마다
# 쓰는 기호와 그 의미가 다르므로, 문서별로 범례를 파싱해 기호->의미를 알아낸다.
LEGEND_SYMBOLS = "♤◎★△□◇◆♧♣●○◈"
LEGEND_ENTRY_RE = re.compile(
    r"([" + re.escape(LEGEND_SYMBOLS) + r"])\s*([^,♤◎★△□◇◆♧♣●○◈]{2,30}?)(?=[,，]|\s*[" + re.escape(LEGEND_SYMBOLS) + r"]|$)"
)


def parse_legend(doc_text: str) -> dict[str, str]:
    idx = doc_text.find("범례")
    if idx < 0:
        return {}
    window = doc_text[idx : idx + 400]
    legend: dict[str, str] = {}
    for match in LEGEND_ENTRY_RE.finditer(window):
        symbol, meaning = match.group(1), match.group(2).strip()
        if meaning:
            legend[symbol] = meaning
    return legend


def legend_symbol_program_types(legend: dict[str, str]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for symbol, meaning in legend.items():
        types: set[str] = set()
        if "복수전공" in meaning or "다중전공" in meaning:
            types.add("dual_major")
        if "부전공" in meaning:
            types.add("minor")
        if types:
            mapping[symbol] = types
    return mapping


def marker_program_types(context: str, symbol_types: dict[str, set[str]]) -> set[str]:
    found: set[str] = set()
    for symbol, types in symbol_types.items():
        if symbol in context:
            found |= types
    return found


def infer_recommended_period(value: str) -> tuple[str, str]:
    year_match = re.search(r"([1-4])\s*학년", value)
    semester_match = re.search(r"([12])\s*학기", value)
    return (
        f"{year_match.group(1)}학년" if year_match else "",
        f"{semester_match.group(1)}학기" if semester_match else "",
    )


def infer_year(value: str) -> str:
    match = re.search(r"(20\d{2})", value)
    return match.group(1) if match else ""


def infer_credit(value: str) -> str:
    patterns = [
        r"(\d+)\s*-\s*\d+\s*-\s*\d+",
        r"(\d+)\s*학점",
        r"\|\s*(\d+)\s*\|",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return ""


def build_catalog_name_lookup(catalog_index: CourseCatalogIndex) -> dict[str, list[tuple[str, str]]]:
    names = []
    for norm_name, rows in catalog_index.by_name.items():
        if len(norm_name) < 4:
            continue
        display = rows[0].get("course_name", "")
        if display:
            names.append((norm_name, display))
    names.sort(key=lambda item: len(item[0]), reverse=True)
    lookup: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for norm_name, display in names:
        for char in set(norm_name):
            lookup[char].append((norm_name, display))
    return lookup


def source_type_from_suffix(suffix: str) -> str:
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".txt":
        return "text"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".hwp", ".hwpx"}:
        return "hwp"
    if suffix in {".xls", ".xlsx", ".csv"}:
        return "spreadsheet"
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
        return "image"
    return "other"


def display_path(path: Path) -> str:
    text = str(path)
    return text[3:] if text.startswith("../") else text


def normalize_for_match(value: str) -> str:
    value = value.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV")
    return re.sub(r"[\s:()（）·ㆍ・.,/\-_\[\]{}<>|\"'“”‘’]", "", value or "").lower()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_department_json(
    target: DepartmentTarget,
    docs: list[SourceDoc],
    course_rows: list[dict[str, str]],
    rule_rows: list[dict[str, str]],
    status_rows: list[dict[str, str]],
) -> None:
    output = target.folder_path / "02_rule_candidates" / "structured_curriculum_candidates.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        output,
        {
            "department": {
                "college": target.college,
                "department_code": target.department_code,
                "department_name": target.department_name,
            },
            "summary": {
                "sources": len(docs),
                "course_candidates": len(course_rows),
                "text_rule_candidates": len(rule_rows),
                "source_statuses": dict(Counter(row["extraction_status"] for row in status_rows)),
                "source_types": dict(Counter(row["source_type"] for row in status_rows)),
            },
            "source_status": status_rows,
            "course_candidates": course_rows,
            "text_rule_candidates": rule_rows,
        },
    )


def write_readme(output_dir: Path) -> None:
    (output_dir / "README.md").write_text(
        """# 학과별 교육과정 구조화 후보

이 폴더는 HTML/PDF/HWP/이미지/스프레드시트 원문에서 추출한 교육과정/졸업요건 후보를 모은다.

- `curriculum_course_candidates.csv`: 교양필수, 교양선택, 전공기초, 전공필수, 전공선택, 부전공/복수전공 요건에 연결될 수 있는 과목 후보.
- `curriculum_text_rule_candidates.csv`: 과목 행으로 바로 만들기 어려운 졸업요건, 신청조건, 이수학점, 제출서류 등 텍스트 규칙 후보.
- `source_extraction_status.csv`: 원문 파일별 추출 성공/실패/파서 필요 상태. 이미지 원문은 macOS Vision OCR을 시도한다.

모든 행은 검증 후보이며, DB에 넣기 전 `needs_review`, `review_reason`, `matched_course_code`를 확인해야 한다.
""",
        encoding="utf-8",
    )


def group_by_code(rows: list[dict[str, str]], code_key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get(code_key):
            grouped[row[code_key]].append(row)
    return grouped


if __name__ == "__main__":
    main()

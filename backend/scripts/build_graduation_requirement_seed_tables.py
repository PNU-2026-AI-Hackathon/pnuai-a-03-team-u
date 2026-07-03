"""Build reviewable graduation requirement seed tables from parsed raw data.

The output is intentionally conservative. It does not write to the DB; it
materializes CSVs that can be reviewed and later converted into migrations or
seed upserts.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

ACTIVE_PROGRAMS_PATH = REPO_ROOT / "backend/seeds/academic_programs_2026_active_bachelor.csv"
CURRICULUM_COURSES_PATH = (
    REPO_ROOT
    / "raw_data/parsed_experiments/department_curriculum_courses/department_curriculum_courses.csv"
)
COURSE_CANDIDATES_PATH = (
    REPO_ROOT
    / "raw_data/parsed_experiments/department_curriculum_structured_candidates/curriculum_course_candidates.csv"
)
CATALOG_COURSES_PATH = (
    REPO_ROOT
    / "raw_data/parsed_experiments/department_courses_from_catalog/department_courses_from_catalog.csv"
)
TEXT_RULE_CANDIDATES_PATH = (
    REPO_ROOT
    / "raw_data/parsed_experiments/department_curriculum_structured_candidates/curriculum_text_rule_candidates.csv"
)
REGULATION_CREDIT_ROWS_PATH = (
    REPO_ROOT
    / "raw_data/manual_staging/00_university_regulations/curriculum_operation/"
    "graduation_credit_rows_from_regulation.csv"
)
REGULATION_RULES_PATH = (
    REPO_ROOT
    / "raw_data/manual_staging/00_university_regulations/curriculum_operation/"
    "regulation_key_requirements.csv"
)
UNRESOLVED_PATH = (
    REPO_ROOT
    / "raw_data/parsed_experiments/department_curriculum_official_search/"
    "unresolved_after_regulation_analysis.csv"
)

OUTPUT_DIR = REPO_ROOT / "raw_data/parsed_experiments/graduation_requirement_seed_tables"


CATEGORY_MAP = {
    "교양 필수": "general_required",
    "교양필수": "general_required",
    "교양 선택": "general_elective_area",
    "교양 선택 1)": "general_elective_area",
    "교양 선택 2)": "general_elective_area",
    "교양선택": "general_elective_area",
    "전공 기초": "major_foundation",
    "전공기초": "major_foundation",
    "전공 필수": "major_required",
    "전공필수": "major_required",
    "전공 선택": "major_elective",
    "전공선택": "major_elective",
    "일반 선택": "free_elective",
    "일반선택": "free_elective",
    "교직": "teacher_training",
    # 문맥에 "복수전공"/"부전공"이 함께 등장하는 행이나, 학과 교육과정표의 ♤/◎ 범례
    # 마커에서 나온 후보의 category_for_program() 결과 (예: "전공기초"의 "전공"을
    # "복수전공"/"부전공"으로 치환). program_type이 이미 dual/minor로 구분돼 있으니
    # category_code는 primary와 같은 major_* 코드로 통일한다.
    "복수전공기초": "major_foundation",
    "복수전공필수": "major_required",
    "복수전공선택": "major_elective",
    "부전공기초": "major_foundation",
    "부전공필수": "major_required",
    "부전공선택": "major_elective",
    # 카테고리 키워드를 못 찾은 폴백 (infer_requirement_category 참고). 구체 분류가
    # 아니라 판정에 그대로 쓸 수 없으니 unknown으로 남겨 사람 검토 대상임을 표시한다.
    "졸업요건": "unknown",
    "복수전공요건": "unknown",
    "부전공요건": "unknown",
    "기초교양": "general_elective_area",
    "unknown": "unknown",
}

REGULATION_CATEGORY_COLUMNS = {
    "hyowon_core": ("general_core", "효원핵심"),
    "hyowon_balanced": ("general_balanced", "효원균형"),
    "hyowon_creative": ("general_creative", "효원창의"),
    "general_education_total": ("general_total", "교양 합계"),
    "major_foundation": ("major_foundation", "전공기초"),
    "major_required": ("major_required", "전공필수"),
    "major_elective": ("major_elective", "전공선택"),
    "minimum_major_total": ("minimum_major_total", "최소전공"),
    "deep_major": ("deep_major", "심화전공"),
    "major_total": ("major_total", "전공 합계"),
    "general_elective": ("free_elective", "일반선택"),
    "teacher_training": ("teacher_training", "교직"),
}


@dataclass(frozen=True)
class Program:
    code: str
    college: str
    name: str
    display_name: str
    feature: str
    duration: str
    degree_level: str


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def normalize_name(value: str | None) -> str:
    return re.sub(r"[\s()·ㆍ・\-_]+", "", value or "").lower()


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]}"


def parse_credit(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    if "/" in text:
        return None
    match = re.match(r"^(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))


def source_ref(value: str | None) -> str:
    if not value:
        return ""
    path = str(value)
    marker = "raw_data/"
    if marker in path:
        return path[path.index(marker) :]
    return path


def load_programs() -> tuple[list[Program], dict[str, Program], dict[str, list[Program]]]:
    rows = read_csv(ACTIVE_PROGRAMS_PATH)
    programs: list[Program] = []
    by_code: dict[str, Program] = {}
    by_name: dict[str, list[Program]] = defaultdict(list)
    for row in rows:
        program = Program(
            code=row["academic_program_code"],
            college=row.get("college_name", ""),
            name=row.get("program_name", ""),
            display_name=row.get("display_name", ""),
            feature=row.get("program_feature_name", ""),
            duration=row.get("duration_name", ""),
            degree_level=row.get("degree_level", ""),
        )
        programs.append(program)
        by_code[program.code] = program
        by_name[normalize_name(program.name)].append(program)
    return programs, by_code, by_name


def map_program_by_name(name: str, by_name: dict[str, list[Program]]) -> Program | None:
    candidates = by_name.get(normalize_name(name), [])
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        bachelors = [p for p in candidates if p.degree_level == "학사"]
        if len(bachelors) == 1:
            return bachelors[0]
    return None


def program_type_for(program: Program) -> str:
    if program.feature == "계약학과":
        return "contract"
    return "primary"


def regulation_program_type(value: str | None, default: str = "primary") -> str:
    if value == "minor":
        return "minor"
    if value == "dual_major":
        return "dual"
    if value == "contract":
        return "contract"
    return default


def build_requirement_sets(
    programs: list[Program],
    regulation_rows: list[dict[str, str]],
    by_name: dict[str, list[Program]],
    unresolved_names: set[str],
    candidate_rows: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, object]], dict[tuple[str, str, str], str]]:
    regulation_by_code: dict[str, dict[str, str]] = {}
    for row in regulation_rows:
        if row.get("program_type") in {"minor", "dual_major"}:
            continue
        program = map_program_by_name(row.get("program_name", ""), by_name)
        if program:
            regulation_by_code[program.code] = row

    rows: list[dict[str, object]] = []
    key_to_id: dict[tuple[str, str, str], str] = {}
    for program in programs:
        curriculum_year = "2026"
        program_type = program_type_for(program)
        reg = regulation_by_code.get(program.code)

        requirement_set_id = stable_id("reqset", program.code, program_type, curriculum_year)
        key_to_id[(program.code, program_type, curriculum_year)] = requirement_set_id
        coverage_status = "needs_review"
        source_priority = "parsed_department_sources"
        source_file = ""
        total_credits = ""
        notes = ""

        if reg:
            coverage_status = "regulation_credit_row_found"
            source_priority = "university_regulation"
            source_file = reg.get("source_file", "")
            total_credits = reg.get("total_credits", "")
            notes = reg.get("notes", "")
        if program.name in unresolved_names:
            coverage_status = "source_still_unresolved"

        rows.append(
            {
                "requirement_set_id": requirement_set_id,
                "academic_program_code": program.code,
                "college_name": program.college,
                "program_name": program.name,
                "display_name": program.display_name,
                "program_type": program_type,
                "curriculum_year": curriculum_year,
                "name": f"{program.name} {curriculum_year} 졸업요건 후보",
                "required_total_credits": total_credits,
                "source_priority": source_priority,
                "coverage_status": coverage_status,
                "source_file": source_file,
                "notes": notes,
            }
        )

    for reg in regulation_rows:
        if reg.get("program_type") not in {"minor", "dual_major"}:
            continue
        program = map_program_by_name(reg.get("program_name", ""), by_name)
        if not program:
            continue
        curriculum_year = "2026"
        program_type = regulation_program_type(reg.get("program_type"))
        requirement_set_id = stable_id("reqset", program.code, program_type, curriculum_year)
        key_to_id[(program.code, program_type, curriculum_year)] = requirement_set_id
        rows.append(
            {
                "requirement_set_id": requirement_set_id,
                "academic_program_code": program.code,
                "college_name": program.college,
                "program_name": program.name,
                "display_name": program.display_name,
                "program_type": program_type,
                "curriculum_year": curriculum_year,
                "name": f"{program.name} {curriculum_year} {program_type} 졸업요건 후보",
                "required_total_credits": reg.get("total_credits", ""),
                "source_priority": "university_regulation",
                "coverage_status": "regulation_credit_row_found",
                "source_file": reg.get("source_file", ""),
                "notes": reg.get("notes", ""),
            }
        )

    # 운영규정 PDF에 복수전공/부전공 학점표가 없어도, 학과 교육과정표 자체에 ♤/◎ 같은
    # 범례 마커로 복수전공/부전공 필수과목이 표시된 경우가 많다 (build_department_curriculum_
    # structured_candidates.py의 marker_program_types 참고). 그 후보에서 마커가 잡힌
    # 학과는 규정표가 없어도 최소한의 요건 세트를 만들어 필수과목을 담을 곳을 마련한다.
    by_code = {program.code: program for program in programs}
    for row in candidate_rows or []:
        candidate_type = row.get("program_type")
        if candidate_type not in {"minor", "dual_major"}:
            continue
        program = by_code.get(row.get("department_code", ""))
        if not program:
            continue
        curriculum_year = "2026"
        program_type = regulation_program_type(candidate_type)
        if (program.code, program_type, curriculum_year) in key_to_id:
            continue
        requirement_set_id = stable_id("reqset", program.code, program_type, curriculum_year)
        key_to_id[(program.code, program_type, curriculum_year)] = requirement_set_id
        rows.append(
            {
                "requirement_set_id": requirement_set_id,
                "academic_program_code": program.code,
                "college_name": program.college,
                "program_name": program.name,
                "display_name": program.display_name,
                "program_type": program_type,
                "curriculum_year": curriculum_year,
                "name": f"{program.name} {curriculum_year} {program_type} 졸업요건 후보 (학과 교육과정표 범례 마커 기반)",
                "required_total_credits": "",
                "source_priority": "parsed_department_source_marker",
                "coverage_status": "needs_review",
                "source_file": "",
                "notes": "학과 자체 교육과정표의 ♤/◎류 범례 마커에서 발견된 필수과목 후보. 총 이수학점 기준은 원문 확인 필요.",
            }
        )
    return rows, key_to_id


def build_category_rows(
    requirement_sets: list[dict[str, object]],
    key_to_id: dict[tuple[str, str, str], str],
    regulation_rows: list[dict[str, str]],
    course_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    catalog_rows: list[dict[str, str]],
    by_name: dict[str, list[Program]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for row in regulation_rows:
        program = map_program_by_name(row.get("program_name", ""), by_name)
        if not program:
            continue
        program_type = regulation_program_type(row.get("program_type"), program_type_for(program))
        reqset_id = key_to_id.get((program.code, program_type, "2026"))
        if not reqset_id:
            continue
        if row.get("program_type") in {"minor", "dual_major"} and row.get("total_credits"):
            category_code = "minor_total" if program_type == "minor" else "dual_major_total"
            category_name = "부전공 총학점" if program_type == "minor" else "복수전공 총학점"
            raw_value = row["total_credits"]
            key = (reqset_id, category_code, "minimum_credits", raw_value)
            if key not in seen:
                seen.add(key)
                rows.append(
                    {
                        "category_requirement_id": stable_id("catreq", reqset_id, category_code, raw_value),
                        "requirement_set_id": reqset_id,
                        "academic_program_code": program.code,
                        "program_name": program.name,
                        "program_type": program_type,
                        "category_code": category_code,
                        "category_name": category_name,
                        "minimum_credits": raw_value,
                        "rule_type": "minimum_credits",
                        "source_kind": "university_regulation",
                        "source_file": row.get("source_file", ""),
                        "needs_review": "N",
                        "review_reason": "",
                        "notes": row.get("notes", ""),
                    }
                )
        for column, (category_code, category_name) in REGULATION_CATEGORY_COLUMNS.items():
            raw_value = row.get(column, "")
            if not raw_value or raw_value == "-":
                continue
            key = (reqset_id, category_code, "minimum_credits", raw_value)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "category_requirement_id": stable_id("catreq", reqset_id, category_code, raw_value),
                    "requirement_set_id": reqset_id,
                    "academic_program_code": program.code,
                    "program_name": program.name,
                    "program_type": program_type,
                    "category_code": category_code,
                    "category_name": category_name,
                    "minimum_credits": raw_value,
                    "rule_type": "minimum_credits",
                    "source_kind": "university_regulation",
                    "source_file": row.get("source_file", ""),
                    "needs_review": "N" if "/" not in raw_value else "Y",
                    "review_reason": "split credit notation needs interpretation" if "/" in raw_value else "",
                    "notes": row.get("notes", ""),
                }
            )

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in course_rows:
        code = row.get("department_code", "")
        category = CATEGORY_MAP.get(row.get("category", ""), CATEGORY_MAP.get(row.get("category", "").strip(), "unknown"))
        if code and category != "unknown":
            grouped[(code, category)].append(row)
    for row in candidate_rows:
        code = row.get("department_code", "")
        category = CATEGORY_MAP.get(row.get("requirement_category", ""), "unknown")
        if code and category != "unknown":
            grouped[(code, category)].append(row)
    for row in catalog_rows:
        if row.get("program_match_status") != "matched":
            continue
        code = row.get("department_code", "")
        category = CATEGORY_MAP.get(row.get("category", ""), "unknown")
        if code and category != "unknown":
            grouped[(code, category)].append(row)

    reqsets_by_code = {str(row["academic_program_code"]): row for row in requirement_sets}
    for (code, category_code), items in sorted(grouped.items()):
        reqset = reqsets_by_code.get(code)
        if not reqset:
            continue
        reqset_id = str(reqset["requirement_set_id"])
        key = (reqset_id, category_code, "parsed_course_presence", "")
        if key in seen:
            continue
        seen.add(key)
        unique_courses = {
            (item.get("matched_course_code") or item.get("raw_course_name") or item.get("raw_course_code"), item.get("raw_course_name"))
            for item in items
        }
        rows.append(
            {
                "category_requirement_id": stable_id("catreq", reqset_id, category_code, "parsed"),
                "requirement_set_id": reqset_id,
                "academic_program_code": code,
                "program_name": reqset["program_name"],
                "program_type": reqset["program_type"],
                "category_code": category_code,
                "category_name": category_code,
                "minimum_credits": "",
                "rule_type": "parsed_course_presence",
                "source_kind": "department_curriculum_parse",
                "source_file": "",
                "needs_review": "Y",
                "review_reason": f"{len(unique_courses)} parsed course candidates; credit total not auto-finalized",
                "notes": "",
            }
        )
    return rows


def build_course_rows(
    key_to_id: dict[tuple[str, str, str], str],
    curriculum_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    catalog_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()

    def add(row: dict[str, str], source_table: str) -> None:
        code = row.get("department_code", "")
        if not code:
            return
        program_type = row.get("program_type") or "primary"
        if program_type == "major":
            program_type = "primary"
        elif program_type in {"minor", "dual_major"}:
            program_type = regulation_program_type(program_type)
        curriculum_year = row.get("curriculum_year") or "2026"
        reqset_id = key_to_id.get((code, program_type, curriculum_year)) or key_to_id.get(
            (code, "primary", "2026")
        )
        if not reqset_id:
            return
        category = CATEGORY_MAP.get(
            row.get("category", "") or row.get("requirement_category", ""),
            row.get("category", "") or row.get("requirement_category", "") or "unknown",
        )
        raw_name = row.get("raw_course_name", "")
        matched_code = row.get("matched_course_code", "") or row.get("course_code", "")
        matched_name = row.get("matched_course_name", "") or row.get("course_name", "")
        if not raw_name:
            raw_name = matched_name
        key = (
            reqset_id,
            curriculum_year,
            category,
            matched_code,
            raw_name,
            row.get("source_file", ""),
        )
        if key in seen:
            return
        seen.add(key)
        match_status = row.get("match_status", "")
        needs_review = row.get("needs_review", "")
        if match_status and match_status != "matched":
            needs_review = "Y"
        review_reason = row.get("review_reason", "")
        if source_table == "department_courses_from_catalog":
            # 이 소스는 학과 공식 졸업요건 문서가 아니라, 수강편람에 그 학과가 개설한다고
            # 찍힌 과목들을 모아 카탈로그 자체의 교과목구분 태그를 그대로 가져다 쓴 것이다.
            # 여러 학기에 걸친 카탈로그 태그를 섞어 쓰기 때문에(예: 전공선택/일반선택 경계가
            # 연도별로 다르게 찍혀있을 수 있음) 실제 학과 요건과 다를 수 있어 항상 사람 검토가
            # 필요하다고 표시한다.
            needs_review = "Y"
            review_reason = (
                (review_reason + " | " if review_reason else "")
                + "source_table=department_courses_from_catalog: 학과 공식 교육과정표가 아니라 "
                "수강편람 카탈로그의 교과목구분 태그로 추정한 후보라 검토 필요"
            )
        rows.append(
            {
                "requirement_course_id": stable_id("reqcourse", *key),
                "requirement_set_id": reqset_id,
                "academic_program_code": code,
                "college_name": row.get("college", ""),
                "program_name": row.get("department_name", ""),
                "program_type": program_type,
                "curriculum_year": curriculum_year,
                "category_code": category,
                "recommended_year": row.get("recommended_year", ""),
                "recommended_semester": row.get("recommended_semester", ""),
                "raw_course_code": row.get("raw_course_code", "") or row.get("source_course_code", ""),
                "raw_course_name": raw_name,
                "raw_credit": row.get("raw_credit", "") or row.get("credits", ""),
                "matched_course_code": matched_code,
                "matched_course_name": matched_name,
                "match_status": match_status or row.get("program_match_status", ""),
                "match_method": row.get("match_method", "") or ("catalog_department_code" if row.get("program_match_status") == "matched" else ""),
                "matched_terms": row.get("matched_terms", "") or row.get("offered_terms", ""),
                "matched_departments": row.get("matched_departments", "") or row.get("catalog_department_name", ""),
                "choice_rule_types": row.get("choice_rule_types", ""),
                "choice_rule_raw": row.get("choice_rule_raw", ""),
                "source_table": source_table,
                "source_file": source_ref(row.get("source_file", "")),
                "needs_review": needs_review or "N",
                "review_reason": review_reason,
            }
        )

    for curriculum_row in curriculum_rows:
        add(curriculum_row, "department_curriculum_courses")
    for candidate_row in candidate_rows:
        add(candidate_row, "curriculum_course_candidates")
    for catalog_row in catalog_rows:
        if catalog_row.get("program_match_status") == "matched":
            add(catalog_row, "department_courses_from_catalog")
    return rows


def build_rule_rows(
    key_to_id: dict[tuple[str, str, str], str],
    text_rows: list[dict[str, str]],
    regulation_rules: list[dict[str, str]],
    by_name: dict[str, list[Program]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()

    for row in text_rows:
        code = row.get("department_code", "")
        program_type = row.get("program_type") or "primary"
        if program_type == "major":
            program_type = "primary"
        reqset_id = key_to_id.get((code, program_type, "2026")) or key_to_id.get((code, "primary", "2026"))
        if not reqset_id:
            continue
        category = CATEGORY_MAP.get(row.get("requirement_category", ""), row.get("requirement_category", "") or "unknown")
        raw_text = row.get("raw_text", "")
        key = (reqset_id, category, raw_text)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "text_rule_id": stable_id("txtrule", *key),
                "requirement_set_id": reqset_id,
                "academic_program_code": code,
                "program_name": row.get("department_name", ""),
                "program_type": program_type,
                "category_code": category,
                "rule_text": raw_text,
                "rule_field": "",
                "rule_value": "",
                "source_kind": row.get("source_type", ""),
                "source_file": source_ref(row.get("source_file", "")),
                "source_title": row.get("source_title", ""),
                "needs_review": row.get("needs_review", "Y") or "Y",
                "review_reason": row.get("review_reason", ""),
            }
        )

    for row in regulation_rules:
        program_name = row.get("program_name", "")
        program = map_program_by_name(program_name, by_name) if program_name else None
        code = program.code if program else ""
        reqset_id = ""
        if program:
            reqset_id = key_to_id.get((program.code, program_type_for(program), "2026"), "")
        key = (reqset_id or "unscoped", row.get("field", ""), row.get("value", ""))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "text_rule_id": stable_id("txtrule", *key),
                "requirement_set_id": reqset_id,
                "academic_program_code": code,
                "program_name": program_name,
                "program_type": row.get("program_type", ""),
                "category_code": row.get("requirement_category", ""),
                "rule_text": row.get("notes", ""),
                "rule_field": row.get("field", ""),
                "rule_value": row.get("value", ""),
                "source_kind": "university_regulation",
                "source_file": row.get("source_file", ""),
                "source_title": row.get("source_title", ""),
                "needs_review": "N" if reqset_id else "Y",
                "review_reason": "" if reqset_id else "unscoped university-wide rule or program name not mapped",
            }
        )
    return rows


def build_coverage_rows(
    requirement_sets: list[dict[str, object]],
    course_rows: list[dict[str, object]],
    category_rows: list[dict[str, object]],
    rule_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    courses_by_reqset = Counter(str(row["requirement_set_id"]) for row in course_rows)
    matched_courses_by_reqset = Counter(
        str(row["requirement_set_id"]) for row in course_rows if row.get("match_status") == "matched"
    )
    categories_by_reqset = Counter(str(row["requirement_set_id"]) for row in category_rows)
    rules_by_reqset = Counter(str(row["requirement_set_id"]) for row in rule_rows if row.get("requirement_set_id"))

    rows = []
    for reqset in requirement_sets:
        reqset_id = str(reqset["requirement_set_id"])
        course_count = courses_by_reqset[reqset_id]
        matched_count = matched_courses_by_reqset[reqset_id]
        category_count = categories_by_reqset[reqset_id]
        rule_count = rules_by_reqset[reqset_id]
        if reqset["coverage_status"] == "source_still_unresolved":
            review_status = "missing_source"
        elif course_count and category_count:
            review_status = "ready_for_human_review"
        elif category_count:
            review_status = "credit_summary_only"
        elif course_count:
            review_status = "course_candidates_only"
        else:
            review_status = "no_parsed_requirements_yet"
        rows.append(
            {
                "requirement_set_id": reqset_id,
                "academic_program_code": reqset["academic_program_code"],
                "program_name": reqset["program_name"],
                "program_type": reqset["program_type"],
                "coverage_status": reqset["coverage_status"],
                "review_status": review_status,
                "category_requirement_count": category_count,
                "course_candidate_count": course_count,
                "matched_course_candidate_count": matched_count,
                "text_rule_count": rule_count,
                "required_total_credits": reqset["required_total_credits"],
                "notes": reqset["notes"],
            }
        )
    return rows


def main() -> None:
    programs, _by_code, by_name = load_programs()
    regulation_rows = read_csv(REGULATION_CREDIT_ROWS_PATH)
    regulation_rules = read_csv(REGULATION_RULES_PATH)
    curriculum_rows = read_csv(CURRICULUM_COURSES_PATH)
    candidate_rows = read_csv(COURSE_CANDIDATES_PATH)
    catalog_rows = read_csv(CATALOG_COURSES_PATH)
    text_rows = read_csv(TEXT_RULE_CANDIDATES_PATH)
    unresolved_names = {row.get("program_name", "") for row in read_csv(UNRESOLVED_PATH)}

    requirement_sets, key_to_id = build_requirement_sets(
        programs, regulation_rows, by_name, unresolved_names, candidate_rows
    )
    category_rows = build_category_rows(
        requirement_sets,
        key_to_id,
        regulation_rows,
        curriculum_rows,
        candidate_rows,
        catalog_rows,
        by_name,
    )
    course_rows = build_course_rows(key_to_id, curriculum_rows, candidate_rows, catalog_rows)
    rule_rows = build_rule_rows(key_to_id, text_rows, regulation_rules, by_name)
    coverage_rows = build_coverage_rows(requirement_sets, course_rows, category_rows, rule_rows)

    write_csv(
        OUTPUT_DIR / "requirement_sets_seed_candidates.csv",
        requirement_sets,
        [
            "requirement_set_id",
            "academic_program_code",
            "college_name",
            "program_name",
            "display_name",
            "program_type",
            "curriculum_year",
            "name",
            "required_total_credits",
            "source_priority",
            "coverage_status",
            "source_file",
            "notes",
        ],
    )
    write_csv(
        OUTPUT_DIR / "requirement_category_seed_candidates.csv",
        category_rows,
        [
            "category_requirement_id",
            "requirement_set_id",
            "academic_program_code",
            "program_name",
            "program_type",
            "category_code",
            "category_name",
            "minimum_credits",
            "rule_type",
            "source_kind",
            "source_file",
            "needs_review",
            "review_reason",
            "notes",
        ],
    )
    write_csv(
        OUTPUT_DIR / "requirement_course_seed_candidates.csv",
        course_rows,
        [
            "requirement_course_id",
            "requirement_set_id",
            "academic_program_code",
            "college_name",
            "program_name",
            "program_type",
            "curriculum_year",
            "category_code",
            "recommended_year",
            "recommended_semester",
            "raw_course_code",
            "raw_course_name",
            "raw_credit",
            "matched_course_code",
            "matched_course_name",
            "match_status",
            "match_method",
            "matched_terms",
            "matched_departments",
            "choice_rule_types",
            "choice_rule_raw",
            "source_table",
            "source_file",
            "needs_review",
            "review_reason",
        ],
    )
    write_csv(
        OUTPUT_DIR / "requirement_text_rule_seed_candidates.csv",
        rule_rows,
        [
            "text_rule_id",
            "requirement_set_id",
            "academic_program_code",
            "program_name",
            "program_type",
            "category_code",
            "rule_text",
            "rule_field",
            "rule_value",
            "source_kind",
            "source_file",
            "source_title",
            "needs_review",
            "review_reason",
        ],
    )
    write_csv(
        OUTPUT_DIR / "requirement_seed_coverage_report.csv",
        coverage_rows,
        [
            "requirement_set_id",
            "academic_program_code",
            "program_name",
            "program_type",
            "coverage_status",
            "review_status",
            "category_requirement_count",
            "course_candidate_count",
            "matched_course_candidate_count",
            "text_rule_count",
            "required_total_credits",
            "notes",
        ],
    )

    summary = {
        "requirement_sets": len(requirement_sets),
        "category_requirements": len(category_rows),
        "course_candidates": len(course_rows),
        "text_rules": len(rule_rows),
        "coverage_status_counts": Counter(str(row["coverage_status"]) for row in requirement_sets),
        "review_status_counts": Counter(str(row["review_status"]) for row in coverage_rows),
        "outputs": [path.name for path in sorted(OUTPUT_DIR.glob("*.csv"))],
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


_CREDIT_PATTERN = re.compile(r"^\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?-\d+(?:\.\d+)?)?$")
_TRACK_YEAR_PATTERN = re.compile(r"(?P<year>\d{4})학년도")


@dataclass(frozen=True)
class RequirementNormalizerContext:
    college: str | None = None
    department_code: str | None = None
    department_name: str | None = None


class GraduationRequirementNormalizer:
    """Normalize department curriculum requirement source files into one JSON shape.

    This first implementation is intentionally deterministic: HTML tables and notes
    are extracted into evidence-rich JSON without asking an LLM to invent missing
    graduation rules. Later LLM/embedding steps can consume this normalized shape.
    """

    schema_version = "graduation_requirement_normalized.v1"

    def normalize_directory(
        self,
        source_dir: Path,
        context: RequirementNormalizerContext | None = None,
    ) -> dict[str, Any]:
        context = context or RequirementNormalizerContext()
        html_files = sorted(
            path for path in source_dir.glob("*.html") if not path.name.startswith(".")
        )
        documents = [self.normalize_html_file(path, source_dir, context) for path in html_files]
        return {
            "schema_version": self.schema_version,
            "source_type": "department_graduation_requirement_sources",
            "college": context.college,
            "department_code": context.department_code,
            "department_name": context.department_name,
            "documents": documents,
            "validation": self._validate_documents(documents),
        }

    def normalize_html_file(
        self,
        path: Path,
        source_root: Path,
        context: RequirementNormalizerContext,
    ) -> dict[str, Any]:
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        title = self._clean_text(soup.title.get_text(" ", strip=True) if soup.title else path.stem)
        h2_nodes = soup.select("h2")
        tables = soup.select("table")
        course_plans = []
        notes = []

        for index, table in enumerate(tables):
            heading = self._nearest_previous_heading(table)
            table_grid = self._table_to_grid(table)
            parsed_table = self._parse_curriculum_table(table_grid)
            course_plans.append(
                {
                    "section_title": heading or self._heading_for_table(h2_nodes, index),
                    "table_index": index,
                    "caption": self._table_caption(table),
                    "headers": parsed_table["headers"],
                    "rows": parsed_table["rows"],
                }
            )

            note = self._nearest_following_note(table)
            if note:
                notes.append(
                    {
                        "after_table_index": index,
                        "section_title": heading or self._heading_for_table(h2_nodes, index),
                        "text": note,
                    }
                )

        return {
            "source_file": str(path.relative_to(source_root)),
            "source_path": str(path),
            "document_title": title,
            "track": self._infer_track(title),
            "course_plans": course_plans,
            "notes": notes,
            "extraction_status": {
                "needs_review": True,
                "reasons": [
                    "졸업 총 이수학점, 영역별 최소학점, 예외규칙은 표에서 명시적으로 확정하지 않고 원문 근거로 보존했습니다.",
                    "교과목명과 학점은 HTML 표 구조에서 추출했으며, 최종 졸업요건 판정 전 사람이 검수해야 합니다.",
                ],
            },
        }

    def dumps(self, normalized: dict[str, Any]) -> str:
        return json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"

    def _parse_curriculum_table(self, grid: list[list[str]]) -> dict[str, Any]:
        if not grid:
            return {"headers": [], "rows": []}

        headers = [cell for cell in grid[0] if cell]
        semester_headers = self._extract_semester_headers(grid[:2])
        if not semester_headers:
            return self._parse_generic_table(grid)

        rows = []
        active_category = None

        for raw_row in grid[2:]:
            row = [self._clean_text(cell) for cell in raw_row]
            if not any(row):
                continue

            label = row[0] if row else ""
            if label and label != "계":
                active_category = self._compact_text(label)

            if label == "계":
                rows.append(self._parse_total_row(row, active_category, semester_headers))
                continue

            rows.append(self._parse_course_row(row, active_category or label, semester_headers))

        return {"headers": headers, "rows": rows}

    def _parse_course_row(
        self,
        row: list[str],
        category: str,
        semester_headers: list[str],
    ) -> dict[str, Any]:
        semester_entries = []
        cells = row[1:]
        for semester_index, semester in enumerate(semester_headers):
            subject_cell_index = semester_index * 2
            credit_cell_index = subject_cell_index + 1
            subject_raw = cells[subject_cell_index] if subject_cell_index < len(cells) else ""
            credit_raw = cells[credit_cell_index] if credit_cell_index < len(cells) else ""
            semester_entries.append(
                {
                    "semester": semester,
                    "subjects_raw": subject_raw,
                    "credits_raw": credit_raw,
                    "course_items": self._pair_courses_and_credits(subject_raw, credit_raw),
                    "choice_rules": self._extract_choice_rules(subject_raw),
                }
            )

        trailing_total = row[-1] if len(row) > 1 and self._looks_like_credit_value(row[-1]) else None
        return {
            "row_type": "courses",
            "category": self._compact_text(category),
            "semesters": semester_entries,
            "row_total_credits": trailing_total,
        }

    def _parse_total_row(
        self,
        row: list[str],
        category: str | None,
        semester_headers: list[str],
    ) -> dict[str, Any]:
        cells = row[1:]
        semester_totals = []
        for semester_index, semester in enumerate(semester_headers):
            credit_cell_index = semester_index * 2 + 1
            value = cells[credit_cell_index] if credit_cell_index < len(cells) else ""
            semester_totals.append({"semester": semester, "credits": value or None})

        return {
            "row_type": "category_total",
            "category": self._compact_text(category) if category else None,
            "semester_totals": semester_totals,
            "total_credits": row[-1] if len(row) > 1 else None,
        }

    def _parse_generic_table(self, grid: list[list[str]]) -> dict[str, Any]:
        start_index = 1
        headers = [self._compact_text(cell) for cell in grid[0] if cell]
        if (
            len(grid) > 1
            and grid[0]
            and grid[1]
            and self._compact_text(grid[0][0]) == self._compact_text(grid[1][0])
            and any(self._compact_text(cell) for cell in grid[1][1:])
        ):
            headers = [self._compact_text(grid[0][0])]
            headers.extend(self._compact_text(cell) for cell in grid[1][1:] if cell)
            start_index = 2

        rows = []
        for index, raw_row in enumerate(grid[start_index:], start=1):
            row = [self._clean_text(cell) for cell in raw_row]
            if not any(row):
                continue
            cells = []
            for cell_index, value in enumerate(row):
                header = headers[cell_index] if cell_index < len(headers) else f"column_{cell_index + 1}"
                cells.append({"header": header, "value": value})
            rows.append({"row_type": "generic_table_row", "row_index": index, "cells": cells})
        return {"headers": headers, "rows": rows}

    def _table_to_grid(self, table: Any) -> list[list[str]]:
        grid: list[list[str]] = []
        rowspans: dict[tuple[int, int], str] = {}

        for row_index, tr in enumerate(table.find_all("tr")):
            grid_row: list[str] = []
            col_index = 0
            cells = tr.find_all(["th", "td"])

            for cell in cells:
                while (row_index, col_index) in rowspans:
                    grid_row.append(rowspans.pop((row_index, col_index)))
                    col_index += 1

                text = self._cell_text(cell)
                rowspan = int(cell.get("rowspan") or 1)
                colspan = int(cell.get("colspan") or 1)

                for offset in range(colspan):
                    grid_row.append(text if offset == 0 else "")
                    if rowspan > 1:
                        for span_row in range(1, rowspan):
                            rowspans[(row_index + span_row, col_index + offset)] = text if offset == 0 else ""
                    col_index += 1

            while (row_index, col_index) in rowspans:
                grid_row.append(rowspans.pop((row_index, col_index)))
                col_index += 1

            grid.append(grid_row)

        max_width = max((len(row) for row in grid), default=0)
        return [row + [""] * (max_width - len(row)) for row in grid]

    def _extract_semester_headers(self, header_rows: list[list[str]]) -> list[str]:
        if not header_rows:
            return []
        headers = [cell for cell in header_rows[0][1:] if cell]
        return [self._clean_text(header) for header in headers if "학기" in header]

    def _pair_courses_and_credits(self, subjects_raw: str, credits_raw: str) -> list[dict[str, str | None]]:
        subjects = self._split_course_like_lines(subjects_raw)
        credits = self._split_credit_like_lines(credits_raw)
        if credits_raw and not credits:
            return []
        count = max(len(subjects), len(credits))
        return [
            {
                "name": subjects[index] if index < len(subjects) else None,
                "credit": credits[index] if index < len(credits) else None,
            }
            for index in range(count)
        ]

    def _split_course_like_lines(self, value: str) -> list[str]:
        lines = [self._clean_text(line) for line in value.split("\n")]
        return [line for line in lines if self._is_course_like_line(line)]

    def _split_credit_like_lines(self, value: str) -> list[str]:
        tokens = re.split(r"\s+", value.strip())
        return [token for token in tokens if self._looks_like_credit_value(token)]

    def _looks_like_credit_value(self, value: str) -> bool:
        return bool(_CREDIT_PATTERN.match(value.strip()))

    def _extract_choice_rules(self, value: str) -> list[dict[str, Any]]:
        compact = self._compact_text(value)
        rules = []
        if re.search(r"[中중]\s*1", compact):
            rules.append(
                {
                    "rule_type": "choose_n_from_group",
                    "selection_count": 1,
                    "raw_text": value,
                    "needs_review": True,
                    "reason": "HTML drawing characters indicate a choose-one group, but exact option boundaries need review.",
                }
            )
        count_match = re.search(r"(?P<count>\d+)\s*과목\s*수강", compact)
        if count_match:
            rules.append(
                {
                    "rule_type": "take_n_courses",
                    "selection_count": int(count_match.group("count")),
                    "raw_text": value,
                    "needs_review": "미수강 과목 중" in compact,
                    "reason": "The source states a course-count choice rule.",
                }
            )
        return rules

    def _is_course_like_line(self, value: str) -> bool:
        value = self._clean_text(value)
        if not value:
            return False
        if re.fullmatch(r"\d+\)", value):
            return False
        if "中" in value:
            return False
        if re.fullmatch(r"[─━┌┐└┘│┃\s]+", value):
            return False
        return True

    def _infer_track(self, title: str) -> dict[str, Any]:
        year_match = _TRACK_YEAR_PATTERN.search(title)
        admission_type = "transfer" if "편입" in title else "freshman"
        if "교직" in title:
            admission_type = "teacher_certification"
        return {
            "title": title,
            "curriculum_year": year_match.group("year") if year_match else None,
            "admission_type": admission_type,
            "applies_to": title,
        }

    def _nearest_previous_heading(self, node: Any) -> str | None:
        current = node
        while current:
            current = current.find_previous(["h2", "h3", "h4"])
            if current:
                return self._clean_text(current.get_text(" ", strip=True))
        return None

    def _nearest_following_note(self, node: Any) -> str | None:
        current = node
        while current:
            current = current.find_next_sibling()
            if current is None:
                return None
            if getattr(current, "name", None) == "table":
                return None
            if getattr(current, "name", None) in {"p", "div"}:
                text = self._clean_text(current.get_text("\n", strip=True))
                if text and any(marker in text for marker in ("1)", "2)", "※", "*")):
                    return text
        return None

    def _heading_for_table(self, h2_nodes: list[Any], index: int) -> str | None:
        if index < len(h2_nodes):
            return self._clean_text(h2_nodes[index].get_text(" ", strip=True))
        return None

    def _table_caption(self, table: Any) -> str | None:
        caption = table.find("caption")
        if not caption:
            return None
        return self._clean_text(caption.get_text(" ", strip=True))

    def _cell_text(self, cell: Any) -> str:
        text = cell.get_text("\n", strip=True)
        return self._clean_text(text)

    def _clean_text(self, value: str) -> str:
        value = value.replace("\xa0", " ")
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r" *\n *", "\n", value)
        return value.strip()

    def _compact_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", self._clean_text(value)).strip()

    def _validate_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        warnings = []
        if not documents:
            warnings.append("HTML source documents were not found.")
        for document in documents:
            if not document["course_plans"]:
                warnings.append(f"{document['source_file']} has no parsed curriculum tables.")
        return {
            "document_count": len(documents),
            "needs_review": True,
            "warnings": warnings,
        }

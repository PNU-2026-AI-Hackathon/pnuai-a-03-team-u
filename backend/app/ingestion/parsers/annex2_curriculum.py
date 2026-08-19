"""별표2(교육과정표) "영역별 졸업기준 학점" 표 → flat `graduation_requirements` 필드.

입력은 HWP를 변환한 XHTML이다. 앱에 HWP 의존성을 넣지 않으려고 변환은 밖에서 한다:

    backend/.venv/bin/hwp5html --output out_dir 2024교육과정표.hwp

## 왜 이 파서가 필요한가

`graduation_requirements`에 **2024학년도 행이 아예 없어서**, 2024 교육과정을 적용받는
학생이 2026 행으로 조용히 폴백해 판정된다(2026-08-19 실계정에서 확인). 학교
"학생별 적용 교육과정 조회"(One-Stop 메뉴 141)가 이 학생에게 2024를 확정해 주므로,
연도에 맞는 행을 원문에서 만들어 넣는다.

## 최소전공 / 심화전공을 flat 두 컬럼으로 접는 규칙

원문은 전공을 두 축으로 쓴다. 컴퓨터공학전공 2024:

    전공기초 25 + 전공필수(최소전공) 33 = 최소전공인정학점 58
    심화전공 44 = 전공필수 4 + 전공선택 40

flat 컬럼에는 **전공필수 33 / 전공선택 44**로 넣는다. 심화전공 안의 "전공필수 4"를
최소전공에 더해 37/40으로 만들면 안 된다 — 학교 졸업요건 화면이 쓰는 값은
전공필수 33이고 최소전공인정학점 58이다. 심화전공의 4는 최소전공 33과 별개로
심화 블록 안에서 채우는 몫이다.

세부(전공필수 4 / 전공선택 40)는 flat 컬럼으로 표현되지 않으므로, 필요하면
`graduation_requirements.special_rules`에 따로 남긴다.

## 표 구조가 연도마다 다르다

교양 쪽이 2026학년도에 개편됐다.

    2024: 교양필수 | 교양선택
    2026: 효원핵심교양 | 효원균형교양(기초교양) | 효원창의교양

전공·일반선택·총계는 두 연도가 같다(확인: 컴퓨터공학전공 2024/2026 둘 다
최소전공 33, 심화 44, 일반선택 6, 총 133).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


# "영역별 졸업기준 학점" 표를 식별하는 헤더 조각. 첫 행에 전부 들어 있어야 한다.
_HEADER_MARKERS = ("학과", "전 공", "졸업기준")

# "44 (전공필수 4 전공선택 40)" 같은 셀에서 괄호 안 세부를 뽑는다.
_DETAIL_RE = re.compile(r"(전공필수|전공선택)\s*(\d+(?:\.\d+)?)")
# 셀 맨 앞의 대표 학점. "33 (전공필수)" → 33
_LEAD_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Annex2Credits:
    """flat `graduation_requirements` 컬럼에 그대로 대응."""

    department_label: str
    required_total_credits: int
    required_major_foundation: int
    required_major_required: int
    required_major_elective: int
    required_general_required: int
    required_general_elective: int
    required_free_elective: int

    def as_columns(self) -> dict[str, int]:
        return {
            "required_total_credits": self.required_total_credits,
            "required_major_foundation": self.required_major_foundation,
            "required_major_required": self.required_major_required,
            "required_major_elective": self.required_major_elective,
            "required_general_required": self.required_general_required,
            "required_general_elective": self.required_general_elective,
            "required_free_elective": self.required_free_elective,
        }

    def sums_to_total(self) -> bool:
        """하위 항목 합이 총계와 맞는가. 원문 검산용."""
        parts = (
            self.required_major_foundation + self.required_major_required
            + self.required_major_elective + self.required_general_required
            + self.required_general_elective + self.required_free_elective
        )
        return parts == self.required_total_credits


class _TableCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag == "tr" and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def extract_tables(xhtml: str) -> list[list[list[str]]]:
    parser = _TableCollector()
    parser.feed(xhtml)
    return parser.tables


def _lead_number(cell: str) -> float:
    m = _LEAD_NUM_RE.match(cell)
    if not m:
        raise ValueError(f"학점을 읽을 수 없는 셀: {cell!r}")
    return float(m.group(1))


def _split_deep_major(cell: str) -> tuple[float, float]:
    """심화전공 셀을 (전공필수 몫, 전공선택 몫)으로 나눈다.

    "44 (전공필수 4 전공선택 40)" → (4.0, 40.0)

    괄호 세부가 없으면 전부 전공선택으로 본다 — 세부를 안 적은 학과는 심화전공을
    통째로 선택 이수로 두는 경우다. **추측으로 필수에 배분하지 않는다.**
    """
    details = dict(_DETAIL_RE.findall(cell))
    total = _lead_number(cell)
    if not details:
        return 0.0, total
    required = float(details.get("전공필수", 0))
    elective = float(details.get("전공선택", total - required))
    if abs((required + elective) - total) > 0.01:
        raise ValueError(
            f"심화전공 세부 합이 대표값과 다르다: {cell!r} "
            f"(필수 {required} + 선택 {elective} != {total})"
        )
    return required, elective


def find_credit_table(tables: list[list[list[str]]]) -> list[list[str]]:
    for table in tables:
        if table and all(any(mark in cell for cell in table[0]) for mark in _HEADER_MARKERS):
            return table
    raise ValueError("'영역별 졸업기준 학점' 표를 찾지 못했다")


def parse_annex2(xhtml: str) -> Annex2Credits:
    """XHTML에서 영역별 졸업기준 학점을 읽는다.

    데이터 행은 마지막 행이다(헤더가 2~3줄로 병합돼 있다). 셀 개수로 연도 구조를
    구분한다 — 2026학년도는 교양이 3칸(효원핵심/효원균형/효원창의), 그 이전은 2칸.
    """
    table = find_credit_table(extract_tables(xhtml))
    row = table[-1]
    if len(row) == 8:            # 학과 | 교양필수 | 교양선택 | 전공기초 | 최소전공 | 심화전공 | 일반선택 | 총계
        label, gen_req, gen_elec_cells, foundation, minimum, deep, free, total = (
            row[0], row[1], [row[2]], row[3], row[4], row[5], row[6], row[7],
        )
    elif len(row) == 9:          # 2026: 교양이 효원핵심 | 효원균형(기초) | 효원창의
        label, gen_req, gen_elec_cells, foundation, minimum, deep, free, total = (
            row[0], row[1], [row[2], row[3]], row[4], row[5], row[6], row[7], row[8],
        )
    else:
        raise ValueError(f"예상하지 못한 열 수({len(row)}): {row!r}")

    # **최소전공과 심화전공은 서로 다른 축이다. 합치지 않는다.**
    #
    #   전공기초 25 + 전공필수 33 = "최소전공인정학점" 58  ← 학교가 쓰는 단위
    #   심화전공 44 = 전공필수 4 + 전공선택 40             ← 심화로 졸업할 때 더 듣는 몫
    #
    # 그래서 flat 컬럼에는 전공필수=최소전공(33), 전공선택=심화전공 총계(44)로 넣는다.
    # 예전에는 심화전공 안의 전공필수 4를 최소전공에 더해 37/40을 만들었는데, 그러면
    # 학교 판정(전공필수 33)과 4학점 어긋난다. 실계정 대조에서 학교 졸업요건 화면이
    # "전공필수 33", "최소전공인정학점 58"을 그대로 쓰는 걸 확인했다(2026-08-19).
    _split_deep_major(deep)  # 괄호 세부와 대표값이 어긋나면 여기서 잡는다
    major_required = _lead_number(minimum)
    major_elective = _lead_number(deep)

    return Annex2Credits(
        department_label=label,
        required_total_credits=int(_lead_number(total)),
        required_major_foundation=int(_lead_number(foundation)),
        required_major_required=int(major_required),
        required_major_elective=int(major_elective),
        required_general_required=int(_lead_number(gen_req)),
        # 2026은 효원균형 + 효원창의를 합쳐 교양선택으로 본다(기존 시드와 같은 규칙).
        required_general_elective=int(sum(_lead_number(c) for c in gen_elec_cells)),
        required_free_elective=int(_lead_number(free)),
    )


def parse_annex2_file(path: str | Path) -> Annex2Credits:
    return parse_annex2(Path(path).read_text(encoding="utf-8"))

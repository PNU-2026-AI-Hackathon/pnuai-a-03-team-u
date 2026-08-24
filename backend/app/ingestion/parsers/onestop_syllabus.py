"""One-Stop 교수계획표(강의계획서) PDF → 구조화 dict.

`pdftotext -layout`만 쓴다 — 이 PDF는 실제 텍스트 레이어가 있어서 OCR/비전
호출이 필요 없다(크롤러 모듈 docstring 참고).

**표 셀 레이블이 세로 중앙 정렬이라, "레이블 줄 = 그 필드 내용의 시작"이 아니다.**
예: `교수목표`(숫자 매긴 목표 5개, 5줄짜리 셀)는 레이블이 3번째 줄 옆에 찍히고,
`강의개요`(3~4줄짜리 짧은 셀)는 레이블이 마지막 줄 옆에 찍힌다 — 둘 다 "레이블이
셀 세로 중앙에 있다"는 같은 규칙인데 셀 높이가 다르면 레이블 위치가 완전히
달라진다. `pdftotext -layout`은 순수 텍스트 스트림이라 이 세로 중앙 정렬을
복원할 방법이 없다(글자 좌표 기반 재구성은 별도 라이브러리·별도 작업).

그래서 이 파서는 **선수과목/지식이 서로 다른 두 줄짜리 레이블이라 그 사이 내용이
곧 그 필드**라는, 실측으로 확인된 유일하게 안전한 경계만 쓰고(2026-08-24, 자료구조
분반 2개 대조), `교수목표`/`강의개요`는 억지로 정확히 가르지 않는다 — 대신 번호
매긴 목록("1. ...", "2. ...")이 끝나는 지점을 목표/개요 경계로 쓰는 휴리스틱을
쓴다(두 샘플 모두에서 정확히 들어맞았다). 이 구분이 완벽하다고 주장하지 않는다 —
`CourseSyllabus.raw_text`에 원문 전체를 그대로 남겨서, 이 파서가 놓치거나
잘못 자른 내용도 나중에 다시 볼 수 있게 한다.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_COMPETENCY_NAMES = ["지구시민", "소통협력", "지식탐구", "혁신도전", "창의융합"]

_WEEK_LINE_RE = re.compile(r"제\s*(\d+)\s*주")
_NUMBERED_ITEM_RE = re.compile(r"^\s*\d+[.)]\s*")


@dataclass
class ParsedSyllabus:
    phone: str | None = None
    email: str | None = None
    teaching_mode: str | None = None
    evaluation_method: str | None = None
    prerequisites_text: str | None = None
    course_objectives: str | None = None
    course_overview: str | None = None
    textbooks: str | None = None
    core_competencies: list[str] | None = None
    weekly_plan: list[dict] | None = None
    raw_text: str = ""


def _pdf_to_text(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def _find_label_line(lines: list[str], label: str, start: int = 0) -> int | None:
    """`label`로 시작하는(공백 무시) 줄의 인덱스. 못 찾으면 None."""
    for i in range(start, len(lines)):
        if lines[i].strip().startswith(label):
            return i
    return None


def _strip_label(line: str, label: str) -> str:
    return line.strip()[len(label):].strip()


def _join(lines: list[str]) -> str | None:
    text = "\n".join(s for s in (l.strip() for l in lines) if s)
    return text or None


def _parse_contact(lines: list[str]) -> tuple[str | None, str | None, int | None]:
    """"연락처   2299   이메일   lik@pusan.ac.kr" 같은 한 줄에서 뽑는다.

    이 줄의 인덱스도 같이 돌려준다 — 수업방식 내용이 여기서부터 시작한다고 본다
    (그 위는 담당교수/연구실/상담시간 행)."""
    for i, line in enumerate(lines):
        m = re.search(r"연락처\s+(\S+)\s+이메일\s+(\S+)", line)
        if m:
            return m.group(1), m.group(2), i
    return None, None, None


def _find_blank_gap(lines: list[str], start: int, limit: int) -> int | None:
    """`start`부터 `limit` 전까지 훑어서 빈 줄(공백만 있는 줄)의 인덱스를 찾는다.

    표 셀 레이블이 세로 중앙 정렬이라 레이블 위치로 경계를 잡을 수 없는 필드
    (수업방식/평가방법)는, 두 셀 사이에 남는 빈 줄 간격으로 대신 자른다 —
    2026-08-24 실측 샘플 2건 모두 이 간격이 있었다."""
    for i in range(start, min(limit, len(lines))):
        if not lines[i].strip():
            return i
    return None


def _parse_objectives_and_overview(block_lines: list[str]) -> tuple[str | None, str | None]:
    """번호 매긴 목록이 끝나는 지점을 교수목표/강의개요 경계로 쓴다(모듈 docstring 참고)."""
    stripped = [l.strip() for l in block_lines if l.strip()]
    last_numbered_idx = -1
    for i, line in enumerate(stripped):
        if _NUMBERED_ITEM_RE.match(line):
            last_numbered_idx = i
    if last_numbered_idx == -1:
        # 번호 목록이 아예 없으면 전부 개요로 본다 — 목표를 굳이 지어내지 않는다.
        return None, _join(stripped)
    objectives = _join(stripped[: last_numbered_idx + 1])
    overview = _join(stripped[last_numbered_idx + 1:])
    return objectives, overview


def _parse_core_competencies(lines: list[str], header_idx: int) -> list[str] | None:
    """"지구시민 소통협력 지식탐구 혁신도전 창의융합" 헤더 줄과, 그 아래 몇 줄 안에
    나오는 O 표시를 **글자 위치**로 맞춰서 어느 역량인지 찾는다. `pdftotext -layout`이
    칸 간격을 문자 단위로 보존해주는 걸 이용한다 — 폰트가 진짜 고정폭은 아니라서
    완벽하진 않다, O 표시 위치에서 제일 가까운 헤더를 고른다."""
    header_line = lines[header_idx]
    positions = []
    for name in _COMPETENCY_NAMES:
        idx = header_line.find(name)
        if idx >= 0:
            positions.append((idx, name))
    if not positions:
        return None
    marked: list[str] = []
    for offset in range(1, 4):
        if header_idx + offset >= len(lines):
            break
        row = lines[header_idx + offset]
        if "교과목에 따른 핵심역량" in row:
            break
        for m in re.finditer(r"O", row):
            closest = min(positions, key=lambda p: abs(p[0] - m.start()))
            if closest[1] not in marked:
                marked.append(closest[1])
    return marked or None


def _parse_weekly_plan(lines: list[str], start_idx: int) -> list[dict] | None:
    weeks: list[dict] = []
    current_week: str | None = None
    current_content: list[str] = []

    def _flush() -> None:
        if current_week is not None:
            content = _join(current_content)
            if content:
                weeks.append({"week": current_week, "content": content})

    for line in lines[start_idx:]:
        m = _WEEK_LINE_RE.search(line)
        if m and line.strip().startswith("제"):
            _flush()
            current_week = f"제{m.group(1)}주"
            rest = line.strip()[len(current_week):].strip()
            current_content = [rest] if rest else []
        elif current_week is not None:
            stripped = line.strip()
            if stripped and stripped != "(지정보강주)":
                current_content.append(stripped)
    _flush()
    return weeks or None


def parse_syllabus_pdf(pdf_path: Path) -> ParsedSyllabus:
    return parse_syllabus_text(_pdf_to_text(pdf_path))


def parse_syllabus_text(raw_text: str) -> ParsedSyllabus:
    """`pdftotext -layout` 결과 텍스트를 직접 받는 버전 — 테스트에서 PDF/`pdftotext`
    바이너리 없이 이 함수만 고정 텍스트로 검증할 수 있게 분리했다."""
    lines = raw_text.split("\n")

    parsed = ParsedSyllabus(raw_text=raw_text)
    parsed.phone, parsed.email, idx_contact = _parse_contact(lines)

    idx_prereq_start = _find_label_line(lines, "선수과목")
    idx_prereq_end = _find_label_line(lines, "지식", start=idx_prereq_start or 0) \
        if idx_prereq_start is not None else None
    idx_objectives = _find_label_line(lines, "교수목표", start=idx_prereq_end or 0) \
        if idx_prereq_end is not None else _find_label_line(lines, "교수목표")
    idx_competency_header_section = _find_label_line(lines, "교과목과 핵심역량과의 관계")
    idx_textbooks = _find_label_line(lines, "교재 및 참고문헌")
    idx_weekly = _find_label_line(lines, "주별 강의계획")

    # 수업방식/평가방법은 레이블이 셀 세로 중앙에 있어서 레이블 위치로 못 자른다
    # (예: "ㆍ대면"(수업방식 내용) → "수업방식"(레이블) → "ㆍ강의식"(같은 내용)처럼
    # 레이블 앞뒤로 내용이 걸쳐 있다). 대신 두 셀 사이의 빈 줄 간격으로 자른다 —
    # 담당교수 연락처 줄 다음부터 첫 빈 줄까지가 수업방식, 그다음부터 "선수과목"
    # 레이블 전까지가 평가방법이다(2026-08-24 실측 샘플 2건 모두 이 간격이 있었다).
    if idx_contact is not None and idx_prereq_start is not None:
        # 연락처 줄 바로 다음 줄도 대개 빈 줄이다(표 행 사이 여백) — 그 첫 빈 줄을
        # 구분자로 잘못 집지 않도록, 내용이 시작하는 지점부터 간격을 찾는다.
        teaching_start = idx_contact + 1
        while teaching_start < idx_prereq_start and not lines[teaching_start].strip():
            teaching_start += 1
        gap = _find_blank_gap(lines, teaching_start + 1, idx_prereq_start)
        if gap is not None:
            parsed.teaching_mode = _join(lines[teaching_start:gap])
            eval_start = gap
            while eval_start < idx_prereq_start and not lines[eval_start].strip():
                eval_start += 1
            parsed.evaluation_method = _join(lines[eval_start:idx_prereq_start])
        else:
            # 간격을 못 찾으면(다른 포맷) 최소한 전체를 수업방식 쪽에라도 담아서 잃지 않는다.
            parsed.teaching_mode = _join(lines[idx_contact + 1: idx_prereq_start])

    # 선수과목: "선수과목 및" 레이블 줄(레이블 제거) ~ "지식" 레이블 줄(제외) 사이.
    if idx_prereq_start is not None and idx_prereq_end is not None:
        first = _strip_label(lines[idx_prereq_start], "선수과목 및")
        block = [first] + lines[idx_prereq_start + 1: idx_prereq_end]
        parsed.prerequisites_text = _join(block)

    # 교수목표+강의개요: "지식" 레이블 다음부터, 핵심역량/교재 섹션 시작 전까지.
    obj_end = idx_competency_header_section or idx_textbooks or idx_weekly
    if idx_prereq_end is not None and obj_end is not None:
        block = lines[idx_prereq_end + 1: obj_end]
        parsed.course_objectives, parsed.course_overview = _parse_objectives_and_overview(block)
    elif idx_objectives is not None and obj_end is not None:
        # "선수과목 및/지식" 자체가 없는(=선수과목 섹션이 통째로 빈) 드문 케이스 대비.
        block = lines[idx_objectives: obj_end]
        parsed.course_objectives, parsed.course_overview = _parse_objectives_and_overview(block)

    if idx_competency_header_section is not None:
        header_idx = _find_label_line(
            lines, _COMPETENCY_NAMES[0], start=idx_competency_header_section
        )
        if header_idx is not None:
            parsed.core_competencies = _parse_core_competencies(lines, header_idx)

    if idx_textbooks is not None:
        end = idx_weekly if idx_weekly is not None else len(lines)
        parsed.textbooks = _join(lines[idx_textbooks + 1: end])

    if idx_weekly is not None:
        parsed.weekly_plan = _parse_weekly_plan(lines, idx_weekly + 1)

    return parsed

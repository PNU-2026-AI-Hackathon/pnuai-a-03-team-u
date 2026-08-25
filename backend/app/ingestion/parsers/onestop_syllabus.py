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
# One-Stop 템플릿이 학과별 특정 셀에 자동으로 끼워 넣는 장애학생 지원 안내문
# (평가방법/교수목표·강의개요 셀 근처에 흔함, 영문 강의계획서는 영문판 문구를 쓴다).
# 교수가 실제로 쓴 내용이 아니라 PNU가 모든 강의계획서에 공통으로 넣는 문구라 어느
# 필드에도 content로 남으면 안 된다(2026-08-25 실측: 교수가 셀을 비워두면 이
# 안내문만 남아서 course_overview에 그대로 저장됨). 독립된 줄로 오는 경우도 있고,
# 교수가 실제로 쓴 내용 뒤에 같은 줄로 바로 이어 붙는 경우도 있다(실측: "Attitude
# 10%, Attendance 10%, Exam 80% , * Students with disabilities can request...").
# `_strip_accessibility_boilerplate`가 트리거 지점부터 지우고(앞의 실제 내용은
# 남긴다), 문장이 pdftotext 줄바꿈으로 다음 줄까지 이어지면(마침표로 안 끝나면)
# 다음 줄도 같이 지운다.
_ACCESSIBILITY_TRIGGER_RE = re.compile(r"[(\[]?\s*[*·]?\s*(장애학생|Students with disabilities)")
# 교수목표/강의개요/수업방식/평가방법은 표 셀 레이블이 세로 중앙 정렬이라
# (모듈 docstring 참고), 셀 내용이 비어 있으면 레이블 단어가 단독 줄로 남고,
# 내용이 있으면 레이블이 그 내용과 같은 줄 맨 앞에 찍힌다(예: "평가방법     성적은
# 출석...") — 두 경우 다 실제 내용이 아니므로 접두어만 벗겨낸다.
_OBJECTIVES_BLOCK_LABEL_LINES = {"교수목표", "강의개요"}
_TEACHING_EVAL_BLOCK_LABEL_LINES = {"수업방식", "평가방법"}

# 경영대학류 템플릿(2026-08-25 실측: 경영학과 PDF 4건 전수, 같은 구조 확인) —
# 표준 템플릿("교수목표"/"강의개요")과 라벨 이름 자체가 다르다:
# "강의목표"(목표), "주요"+"학습내용"(핵심 내용, 두 조각짜리 라벨),
# "강의개요"+"강의구성"(구성 — 여기선 "강의개요"가 사실상 빈 헤더고 진짜 내용은
# "강의구성" 쪽에 있다). 게다가 선수과목/핵심역량 사이에 경영학 인증(AACSB류)
# 전용 "OO 세부 학습성과 목표" 표(BL 1-1 등)가 끼어 있어서 표준 템플릿의
# "지식 다음부터 핵심역량 전까지 = 교수목표+강의개요" 가정이 아예 안 맞는다.
_BUSINESS_TEMPLATE_NOISE_RE = re.compile(
    r"BL\s*\d+-\d+|밀접\(High\)|보통\(Medium\)|낮음\(Low\)|"
    r"지구시민|소통협력|지식탐구|혁신도전|창의융합|부산대학교|5대\s*핵심역량|"
    r"학습성과\s*목표|상관관계|교육방법|경영학\s*세부"
)
# "지구시민/소통협력/..." 헤더 줄 아래, 어느 역량에 해당하는지 O 표시만 있는 줄
# (예: "  O     O    O      O     O") — 노이즈 키워드가 하나도 없어서 위 정규식으로
# 못 잡는다.
_BUSINESS_TEMPLATE_O_ROW_RE = re.compile(r"^\s*(O\s*)+$")
_BUSINESS_TEMPLATE_LABEL_LINES = {"강의목표", "주요", "학습내용", "강의개요", "강의구성"}


def _is_business_template(lines: list[str]) -> bool:
    """"강의목표" 라벨이 있고 "교수목표" 라벨이 없으면 경영대학류 템플릿으로 본다 —
    지금까지 실측한 표준 템플릿 샘플엔 "강의목표"가 나온 적이 없어 상호 배타적인
    구분자로 쓸 만하다."""
    return (
        _find_label_line(lines, "강의목표") is not None
        and _find_label_line(lines, "교수목표") is None
    )


def _strip_leading_label(line: str, labels: set[str]) -> str:
    for label in labels:
        if line.startswith(label):
            return line[len(label):].strip()
    return line


def _strip_accessibility_boilerplate(lines: list[str]) -> list[str]:
    """장애학생 안내문을 지운다(줄을 통째로 삭제하면 인덱스 기반 로직이 다 깨지므로
    자리는 빈 줄로 남긴다). 트리거 앞에 실제 내용이 있으면 그 부분은 남기고, 트리거
    뒤(같은 줄 나머지 + 문장이 안 끝났으면 다음 줄 전체)는 지운다."""
    out = list(lines)
    for i, line in enumerate(out):
        m = _ACCESSIBILITY_TRIGGER_RE.search(line)
        if not m:
            continue
        out[i] = line[: m.start()].rstrip()
        removed_tail = line[m.start():].strip()
        if not removed_tail.endswith(".") and i + 1 < len(out):
            out[i + 1] = ""
    return out


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


def _collapse_whitespace(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _find_label_line(lines: list[str], label: str, start: int = 0) -> int | None:
    """`label`로 시작하는 줄의 인덱스. 못 찾으면 None.

    라벨 내부 공백까지 없애고 비교한다 — 같은 라벨이 PDF마다 "주별 강의계획"/
    "주별강의계획"처럼 공백 유무가 갈리는 게 실측됐다(2026-08-25, 경영학과
    샘플). 공백 하나라도 다르면 매치가 안 돼서 `idx_weekly`가 None이 되고,
    그 결과 `textbooks` 추출 범위가 문서 끝까지로 번져서 주별 강의계획 표
    전체가 textbooks에 통째로 섞여 들어갔었다."""
    target = _collapse_whitespace(label)
    for i in range(start, len(lines)):
        if _collapse_whitespace(lines[i]).startswith(target):
            return i
    return None


def _strip_label(line: str, label: str) -> str:
    return line.strip()[len(label):].strip()


def _join(lines: list[str]) -> str | None:
    text = "\n".join(s for s in (l.strip() for l in lines) if s)
    return text or None


def _parse_contact(lines: list[str]) -> tuple[str | None, str | None, int | None]:
    """"연락처   2299   이메일   lik@pusan.ac.kr" 같은 한 줄에서 뽑는다.

    이 줄의 인덱스도 같이 돌려준다 — 수업방식/평가방법 내용이 여기서부터 시작한다고
    본다(그 위는 담당교수/연구실/상담시간 행). 교수가 연락처/이메일을 아예 안 채운
    경우도 흔한데(2026-08-25 실측), 예전엔 그때 값 매치 자체가 실패해서 인덱스도
    None이 되는 바람에 실제로 있는 수업방식/평가방법 내용까지 통째로 못 뽑았다 —
    "연락처"·"이메일" 레이블이 있는 줄인지만 보고, 값은 있으면 뽑고 없으면 None으로
    둔다."""
    for i, line in enumerate(lines):
        if "연락처" not in line or "이메일" not in line:
            continue
        m = re.search(r"연락처\s+(\S+)\s+이메일\s+(\S+)", line)
        if m:
            return m.group(1), m.group(2), i
        return None, None, i
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
    """번호 매긴 목록이 끝나는 지점을 교수목표/강의개요 경계로 쓴다(모듈 docstring 참고).

    이 블록엔 "교수목표"/"강의개요" 레이블 단어 자체가 세로 중앙 정렬 때문에 섞여
    들어온다 — 셀이 비어 있으면 레이블만 단독 줄로 남고, 셀에 내용이 있으면
    레이블이 그 줄 맨 앞에 실제 내용과 같은 줄로 찍힌다(예: "강의개요     적용해
    보는 기초적인 실습을...", 2026-08-25 실측 — 레이블 뒤 내용까지 통째로 버리면
    안 된다). 두 경우 다 레이블 접두어만 벗겨낸다. 장애학생 안내문은
    `parse_syllabus_text`가 호출 전에 이미 지워놨다."""
    stripped = [
        s for s in (
            _strip_leading_label(l.strip(), _OBJECTIVES_BLOCK_LABEL_LINES) for l in block_lines
        ) if s
    ]
    last_numbered_idx = -1
    for i, line in enumerate(stripped):
        if _NUMBERED_ITEM_RE.match(line):
            last_numbered_idx = i
    if last_numbered_idx == -1:
        # 번호 목록이 없는 표준 템플릿도 많다. 이때 예전 구현은 목표+개요를 전부
        # ``course_overview``에 넣었는데, C++프로그래밍처럼 목표 문장이 실제로 있는
        # 강좌의 추천 근거가 뭉개졌다. 표 레이블이 세로 중앙에 있어 ``강의개요``
        # 위치만으로는 경계가 불완전하므로, 다음의 보수적 규칙을 쓴다.
        #
        # - 교수목표 라벨 뒤의 연속된 '학습한다/기른다/이해한다' 문장을 목표로 잡고
        # - 첫 비목표형 주제 나열(예: 'C 언어의 확장') 또는 빈 줄부터 개요로 넘긴다.
        #
        # 목표형 문장을 하나도 확인하지 못하면 목표를 지어내지 않고 기존처럼 전부
        # 개요로 둔다. 원문은 raw_text에 보존되어 있어 이 규칙이 보수적이어도 손실은 없다.
        objective_label_idx = next(
            (i for i, line in enumerate(block_lines) if line.strip().startswith("교수목표")),
            None,
        )
        if objective_label_idx is None:
            return None, _join(stripped)

        def clean(line: str) -> str:
            value = _strip_leading_label(line.strip(), _OBJECTIVES_BLOCK_LABEL_LINES)
            return value.lstrip(":：- ").strip()

        def is_goal_outcome(line: str) -> bool:
            return bool(re.search(
                r"(?:학습한다|이해한다|습득한다|체득한다|배양한다|함양한다|기른다|"
                r"익힌다|훈련한다|숙달한다|강화한다|향상한다|확립한다|목표로 한다|할 수 있다)[.!]?$",
                line,
            ))

        objectives: list[str] = []
        overview_start: int | None = None
        saw_goal_outcome = False
        for i in range(objective_label_idx, len(block_lines)):
            raw = block_lines[i]
            value = clean(raw)
            if not value:
                # 세로 중앙에 놓인 같은 필드 라벨은 목표 셀 한가운데에 다시
                # 나타날 수 있다. 빈 줄과 달리 경계 신호가 아니다.
                if raw.strip() in _OBJECTIVES_BLOCK_LABEL_LINES:
                    continue
                # 제목 다음의 빈 줄은 목표 목록 안에도 흔하다. 실제 목표형 문장을
                # 아직 만나기 전에는 경계로 확정하지 않는다(Modern C++ 템플릿).
                if objectives and saw_goal_outcome:
                    overview_start = i + 1
                    break
                continue
            # 강의개요 라벨이 목표 셀 안으로 세로 이동해도 그 줄 뒤 내용은 개요다.
            if raw.strip().startswith("강의개요"):
                overview_start = i
                break
            if saw_goal_outcome and not is_goal_outcome(value):
                overview_start = i
                break
            objectives.append(value)
            saw_goal_outcome = saw_goal_outcome or is_goal_outcome(value)

        if not saw_goal_outcome:
            return None, _join(stripped)
        overview_lines = block_lines[overview_start:] if overview_start is not None else []
        overview = _join(clean(line) for line in overview_lines)
        return _join(objectives), overview
    objectives = _join(stripped[: last_numbered_idx + 1])
    overview = _join(stripped[last_numbered_idx + 1:])
    return objectives, overview


def _parse_business_template_objectives_and_overview(
    lines: list[str], idx_competency_header_section: int | None
) -> tuple[str | None, str | None]:
    """경영대학류 템플릿 전용(모듈 상단 `_is_business_template` 주석 참고).

    `course_objectives` = "강의목표" 셀. `course_overview` = "주요학습내용"+
    "강의구성" 두 셀을 합친 것 — 표준 템플릿의 "강의개요" 하나가 여기선 이
    두 개로 쪼개져 있어서, 이 파서가 담당하는 두 필드(objectives/overview)에
    맞추려면 이렇게 합칠 수밖에 없다.

    **"강의목표"↔"주요학습내용" 경계는 원문 자체에 뚜렷한 표시가 없다** — 둘 다
    표 셀 세로 중앙 정렬 라벨이고, 실측(2026-08-25, 경영학과 4개 PDF 전수)
    으로는 두 필드가 전환되는 정확한 줄에 빈 줄도 라벨도 없다. "주요" 라벨이
    나오는 위치를 경계로 쓰는데, 이러면 주요학습내용 맨 앞 한두 줄이 강의목표
    쪽으로 새어 들어갈 수 있다 — 완벽한 경계라고 주장하지 않는다(모듈
    docstring과 같은 원칙, `raw_text`에 원문 전체가 그대로 남는다)."""
    idx_goal = _find_label_line(lines, "강의목표")
    idx_main_start = _find_label_line(lines, "주요", start=idx_goal) if idx_goal is not None else None
    idx_overview_label = _find_label_line(lines, "강의개요", start=idx_main_start) if idx_main_start is not None else None
    idx_teaching_mode = _find_label_line(lines, "수업방식", start=idx_overview_label) if idx_overview_label is not None else None

    def _clean_block(block_lines: list[str]) -> str | None:
        filtered = [
            l for l in block_lines
            if not _BUSINESS_TEMPLATE_NOISE_RE.search(l) and not _BUSINESS_TEMPLATE_O_ROW_RE.match(l)
        ]
        stripped = [
            s for s in (_strip_leading_label(l.strip(), _BUSINESS_TEMPLATE_LABEL_LINES) for l in filtered)
            if s
        ]
        return _join(stripped)

    objectives = None
    if idx_competency_header_section is not None and idx_main_start is not None:
        objectives = _clean_block(lines[idx_competency_header_section + 1: idx_main_start])

    overview = None
    if idx_main_start is not None and idx_teaching_mode is not None:
        overview = _clean_block(lines[idx_main_start: idx_teaching_mode])

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
    # 표 행 레이블이 세로 중앙 정렬이라("제N주" 행도 예외 아니다), 그 행의 첫 줄이
    # 레이블보다 먼저 나올 수 있다(예: "[표절, 시험 부정행위 예방교육..." 이 "제1주"
    # 줄보다 위에 있음 — 독립 리뷰 2026-08-24 지적). 아직 어느 주차에도 못 붙인
    # 줄을 여기 모아뒀다가, 첫 "제N주"를 찾으면 그 주차 내용 맨 앞에 붙인다.
    pending_prefix: list[str] = []

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
            current_content = pending_prefix + ([rest] if rest else [])
            pending_prefix = []
        elif current_week is not None:
            stripped = line.strip()
            if stripped and stripped != "(지정보강주)":
                current_content.append(stripped)
        else:
            stripped = line.strip()
            # "주차 / 강의 및 실험 실기 내용 / 과제 및 기타 참고사항" 표 헤더 행은
            # 내용이 아니라 컬럼 이름이다 — 1주차 내용으로 잘못 붙이면 안 된다.
            if stripped and not stripped.startswith("주차"):
                pending_prefix.append(stripped)
    _flush()
    return weeks or None


def parse_syllabus_pdf(pdf_path: Path) -> ParsedSyllabus:
    return parse_syllabus_text(_pdf_to_text(pdf_path))


def parse_syllabus_text(raw_text: str) -> ParsedSyllabus:
    """`pdftotext -layout` 결과 텍스트를 직접 받는 버전 — 테스트에서 PDF/`pdftotext`
    바이너리 없이 이 함수만 고정 텍스트로 검증할 수 있게 분리했다."""
    lines = _strip_accessibility_boilerplate(raw_text.split("\n"))

    parsed = ParsedSyllabus(raw_text=raw_text)
    parsed.phone, parsed.email, idx_contact = _parse_contact(lines)

    idx_prereq_start = _find_label_line(lines, "선수과목")
    idx_prereq_end = _find_label_line(lines, "지식", start=idx_prereq_start or 0) \
        if idx_prereq_start is not None else None
    if idx_prereq_end is None and idx_prereq_start is not None:
        # 선수과목 셀이 완전히 비어 있으면 "선수과목 및 지식" 세 단어가 통째로
        # 두 줄에 걸쳐(예: "선수과목"/"및 지식") 쪼개진다 — "지식"이 줄 맨 앞이
        # 아니라 "및" 뒤에 붙어 나오는 경우까지 다음 몇 줄 안에서 찾는다
        # (실측: 경영대학류 템플릿, 2026-08-25 — 4개 PDF 전수 이 패턴).
        for i in range(idx_prereq_start, min(idx_prereq_start + 4, len(lines))):
            if "지식" in lines[i]:
                idx_prereq_end = i
                break
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
        # 연락처 줄 다음은 종종 이메일이 길어서 다음 줄로 넘어간 나머지 조각처럼
        # 실제 내용이 아닌 짧은 잔재가 남는다(실측: "sanghwa.jeong@pusan.ac.k" /
        # "r"로 이메일이 두 줄에 걸침) — 그 잔재를 수업방식 내용 시작으로 잘못
        # 집으면 안 된다. "연락처" 블록이 끝나는 첫 빈 줄까지는 전부 잔재로 보고
        # 건너뛴 다음, 그 빈 줄 구간도 지나서 진짜 내용이 시작하는 지점을 찾는다.
        i = idx_contact + 1
        while i < idx_prereq_start and lines[i].strip():
            i += 1
        while i < idx_prereq_start and not lines[i].strip():
            i += 1
        teaching_start = i
        gap = _find_blank_gap(lines, teaching_start + 1, idx_prereq_start)
        if gap is not None:
            parsed.teaching_mode = _join([
                _strip_leading_label(l.strip(), _TEACHING_EVAL_BLOCK_LABEL_LINES)
                for l in lines[teaching_start:gap]
            ])
            eval_start = gap
            while eval_start < idx_prereq_start and not lines[eval_start].strip():
                eval_start += 1
            parsed.evaluation_method = _join([
                _strip_leading_label(l.strip(), _TEACHING_EVAL_BLOCK_LABEL_LINES)
                for l in lines[eval_start:idx_prereq_start]
            ])
        else:
            # 간격을 못 찾으면(다른 포맷) 최소한 전체를 수업방식 쪽에라도 담아서 잃지 않는다.
            parsed.teaching_mode = _join([
                _strip_leading_label(l.strip(), _TEACHING_EVAL_BLOCK_LABEL_LINES)
                for l in lines[teaching_start: idx_prereq_start]
            ])

    # 선수과목: "선수과목 및" 레이블 줄(레이블 제거) ~ "지식" 레이블 줄(제외) 사이.
    if idx_prereq_start is not None and idx_prereq_end is not None:
        first = _strip_label(lines[idx_prereq_start], "선수과목 및")
        block = [first] + lines[idx_prereq_start + 1: idx_prereq_end]
        parsed.prerequisites_text = _join(block)

    if _is_business_template(lines):
        # 경영대학류 템플릿(모듈 상단 주석 참고) — "교수목표"/"강의개요" 라벨도,
        # 그 사이 구간 가정("지식" 다음부터 핵심역량 전까지")도 안 맞는다.
        # 전용 함수로 "강의목표"→course_objectives, "주요학습내용"+"강의구성"→
        # course_overview를 따로 뽑는다.
        parsed.course_objectives, parsed.course_overview = (
            _parse_business_template_objectives_and_overview(lines, idx_competency_header_section)
        )
    else:
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

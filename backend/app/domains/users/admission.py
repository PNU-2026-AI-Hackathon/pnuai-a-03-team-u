"""신입학/편입학 구분과 거기서 파생되는 학년 정책.

편입생은 1·2학년 커리큘럼을 밟지 않는다. 로드맵·내 정보 화면은 학년 슬롯을
"입학 전 인정 학점 + 3·4학년"으로 구성해야 하고, AI는 1·2학년 과목을 새로
추천하면 안 된다.

이 정책이 history.py와 roadmap_chat.py에 각각 상수로 박혀 있었는데, 한쪽만
고치면 화면과 AI가 서로 다른 학년을 말하게 된다. 여기로 모은다.
"""

from __future__ import annotations

from typing import Literal

AdmissionType = Literal["freshman", "transfer"]

FRESHMAN: AdmissionType = "freshman"
TRANSFER: AdmissionType = "transfer"

# 편입생이 편성되는 학년. 부산대는 3학년 편입이 표준이라 지금은 하나로 고정한다.
# 2학년 편입까지 받으려면 User에 entry_grade를 따로 두고 이 상수를 대체해야 한다.
TRANSFER_ENTRY_GRADE = 3

# StudentCourseRecord.semester에서 "입학 전 인정 학점"을 뜻하는 값들.
# 정규 학기(1학기/2학기)가 아니라 학년 계산이 불가능한 lump-sum이다.
PRE_ADMISSION_SEMESTERS: frozenset[str] = frozenset({"입학전성적", "편입인정"})


def normalize_admission_type(value: str | None) -> AdmissionType:
    """DB 값 하나를 안전하게 해석한다.

    컬럼이 nullable이라 옛 행은 None이고, 손으로 넣은 오타가 들어올 수도 있다.
    "transfer"가 아닌 모든 값은 신입학으로 본다 — 편입 처리는 1·2학년을 화면에서
    감추는 파괴적인 동작이라, 확신이 없으면 하지 않는 쪽이 안전하다.
    """
    return TRANSFER if value == TRANSFER else FRESHMAN


def is_transfer(value: str | None) -> bool:
    return normalize_admission_type(value) == TRANSFER


def entry_grade(value: str | None) -> int:
    """이 학생의 커리큘럼이 시작되는 학년."""
    return TRANSFER_ENTRY_GRADE if is_transfer(value) else 1


# 학적부 "학적변동" 표의 변동구분 중 편입으로 보는 값. 부산대는 "편입학" 하나로
# 쓰지만 표기가 바뀔 수 있어 부분 일치로 본다("일반편입학" 등).
_TRANSFER_CHANGE_KEYWORD = "편입"


def infer_admission_type_from_status_changes(
    rows: list[dict[str, str]] | None,
) -> AdmissionType | None:
    """학적부 학적변동 내역에서 편입 여부를 판정한다.

    `None`을 돌려주면 "판정하지 않음"이다 — 호출부는 기존 값을 그대로 둬야 한다.
    편입 기록이 없다고 해서 freshman으로 **덮어쓰지 않는다**: 표를 못 읽었거나
    구조가 바뀐 경우와, 진짜 신입학인 경우를 구분할 수 없기 때문이다. 반대 방향
    (freshman → transfer)은 1·2학년을 화면에서 감추는 파괴적인 동작이라
    (`normalize_admission_type` 참고) 편입 행이 확실할 때만 한다.

    취소된 변동(취소여부 Y)은 무시한다 — 편입 신청이 취소된 이력이 남아 있는
    경우까지 편입생으로 보면 안 된다.
    """
    if not rows:
        return None
    for row in rows:
        kind = (row.get("변동구분") or "").strip()
        if _TRANSFER_CHANGE_KEYWORD not in kind:
            continue
        if (row.get("취소여부") or "").strip().upper() == "Y":
            continue
        return TRANSFER
    return None

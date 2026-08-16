"""UserAcademicProgram.status 정책 — 어떤 학적이 판정·추천 대상인가.

## 왜 별도 모듈인가

`status`에는 두 종류의 값이 섞여 들어온다:

1. `"active"` — 가입/학적신청 시 붙는 기본값
2. One-Stop 학적상태 원문 — `map_student_record`가 `"재학"`이 아니면 원문을 그대로 넣는다
   (`"휴학"`, `"자퇴"`, `"제적"`, `"졸업"` 등)

판정 대상 여부를 `status == "active"`로 판단하던 코드가 7곳에 흩어져 있었고, 그래서
**휴학생은 졸업요건 판정이 통째로 비었다** — 로드맵·시간표·졸업 진단 전부. 휴학은
학업을 그만둔 게 아니라 잠시 쉬는 것이라 오히려 "복학하면 뭐가 남았나"를 알아야 한다
(2026-08-14 정책 결정).

정책을 여기 한 곳에 두고 모든 호출부가 이걸 쓰게 한다. 상태값이 추가돼도 한 곳만 고치면 된다.
"""

from __future__ import annotations

# 판정·추천 대상으로 볼 학적 상태.
#
# 휴학을 포함하는 이유: 복학 예정이므로 남은 요건을 알아야 하고, 엇학기 학생 대응
# (`staggered_semester` 규칙)도 애초에 휴학 이력을 전제로 만든 기능이다.
#
# 졸업은 포함하지 않는다 — 이미 요건을 채운 상태라 "남은 학점" 안내가 의미 없고,
# 자퇴·제적은 학적 자체가 없어진 것이라 제외한다.
ACTIVE_PROGRAM_STATUSES: frozenset[str] = frozenset({
    "active",   # 가입/학적신청 기본값
    "재학",
    "휴학",
})


def is_active_program_status(status: str | None) -> bool:
    """이 학적이 판정·추천 대상인지.

    값이 비어 있으면 대상으로 본다 — 옛 행이나 수동 입력으로 status가 안 채워진 경우,
    판정을 빼버리는 것보다 보여주는 쪽이 안전하다(빼면 사용자는 이유도 모른 채
    "데이터가 없습니다"만 본다).
    """
    if not status:
        return True
    return status.strip() in ACTIVE_PROGRAM_STATUSES

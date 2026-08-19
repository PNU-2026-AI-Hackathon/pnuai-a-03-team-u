"""graduation_requirements 스코프 유니크 제약

⚠️ 이 파일은 원래 revision id가 `c3d4e5f6a7b8`이었는데, 그건 2026-07-09
`c3d4e5f6a7b8_add_department_name_and_plan_item_snapshots.py`(PR #51)가 이미 쓰던
id였다. 같은 id를 가진 파일이 둘이 되면서 alembic이 한 노드에 서로 다른 부모를 붙여
**리비전 그래프에 19개짜리 사이클**이 생겼고, `alembic current`/`heads`/`upgrade`가
전부 `CycleDetected`로 죽었다(2026-08-19 발견). id를 새로 발급하고, 갈래를 만들지
않도록 당시 head였던 `8f3c21b47ae0` 뒤로 붙였다.

새 마이그레이션을 만들 때는 id를 손으로 짓지 말고 `alembic revision -m "..."`이
발급하게 할 것.

같은 (program_type, department_id, major_id, curriculum_year) 조합이 두 행 존재하면
판정 엔진이 어느 행을 쓰느냐에 따라 졸업 판정이 달라진다. 실제로 간호학과 dual 2026이
2행이었고, 그 학생은 졸업요건 조회에서 500 에러가 났다(2026-08-13 정리 완료).

**NULLS NOT DISTINCT가 핵심이다.** Postgres에서 `NULL = NULL`은 참이 아니라 NULL이라,
평범한 UNIQUE 인덱스는 NULL이 낀 행들을 전부 "서로 다르다"고 보고 통과시킨다. 그런데
`major_id = NULL`인 행이 363행 중 290행(79%)이고, 정작 중복이 났던 간호학과 행도
major_id=NULL이었다 — 평범한 UNIQUE로는 이 사고를 못 막는다.

여기서 NULL은 "모름"이 아니라 **"이 학과 전체에 공통 적용"** 이라는 확정적 의미이므로
NULLS NOT DISTINCT가 의미상으로도 맞다.

요구사항: PostgreSQL 15+ (NULLS NOT DISTINCT). 운영은 17.6.

Revision ID: 883cd0847a1e
Revises: 8f3c21b47ae0
"""
from alembic import op

revision = "883cd0847a1e"
down_revision = "8f3c21b47ae0"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_graduation_requirements_scope"


def upgrade() -> None:
    # 기존 중복이 있으면 인덱스 생성이 실패한다. 그게 맞는 동작이다 —
    # 조용히 넘어가면 어느 행이 살아남을지 모르는 채로 제약만 생긴다.
    # 정리는 scripts/dedupe_graduation_requirements.py 로 먼저 한다.
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME}
            ON graduation_requirements
               (program_type, department_id, major_id, curriculum_year)
            NULLS NOT DISTINCT
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")

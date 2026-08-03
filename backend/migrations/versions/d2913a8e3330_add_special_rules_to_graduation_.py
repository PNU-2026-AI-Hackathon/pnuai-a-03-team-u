"""add special_rules JSONB to graduation_requirements

부전공/복수전공/SW융합트랙의 이수 규칙(택N/M, exclude_categories 등)을 담기 위한
JSONB 컬럼 추가. flat `required_*_credits` 컬럼만으로는 "5과목 중 3과목 이수",
"전공기초/현장실습 인정 제외" 같은 프로그램별 규칙을 표현할 수 없어 별도 테이블
신설 대신 JSONB로 스키마 진화 여지를 남긴다.

**JSONB 구조 (예시):**
```json
{
  "groups": [
    {"label": "필수", "type": "all"},
    {"label": "택3/5", "type": "min_courses", "n": 3}
  ],
  "exclude_categories": ["전공기초", "현장실습"],
  "min_distinct_departments": 2,
  "notes": "학번별 필수과목 명칭 변경"
}
```

- `groups[*].label`: `program_courses.requirement_group` 값과 매칭되는 조인 키
- `groups[*].type`: 'all' | 'min_courses' | 'min_credits' | 'min_distinct_departments'
- `groups[*].n`: min_courses에서 최소 이수 과목 수
- `groups[*].min_credits`: min_credits에서 최소 학점
- `exclude_categories`: 부전공 이수학점 인정 제외 이수구분 (사회복지 현장실습, 사회학 전공기초 등)

NULL 허용 — 규칙 없는 기존 학과 요건 행은 그대로 두고 SW융합/부전공만 채운다.

Revision ID: d2913a8e3330
Revises: ff48331e2562
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd2913a8e3330'
down_revision: Union[str, Sequence[str], None] = 'ff48331e2562'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'graduation_requirements',
        sa.Column('special_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('graduation_requirements', 'special_rules')

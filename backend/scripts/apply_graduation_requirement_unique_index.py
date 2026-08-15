"""graduation_requirements 스코프 유니크 인덱스를 운영 DB에 반영한다.

## 왜 alembic이 아니라 이 스크립트인가

운영 Supabase의 `alembic_version`이 `8f3c21b47ae0`인데 이 리비전이 로컬
`migrations/versions/`에 없다 — `alembic upgrade`가 "Can't locate revision"으로 실패한다
(알려진 상황). 그래서 **신규 DB용 마이그레이션**(`c3d4e5f6a7b8`)은 그대로 남기고,
운영에는 이 스크립트로 같은 DDL만 직접 반영한다.

## 무엇을 만드나

    CREATE UNIQUE INDEX uq_graduation_requirements_scope
        ON graduation_requirements (program_type, department_id, major_id, curriculum_year)
        NULLS NOT DISTINCT;

`NULLS NOT DISTINCT`가 핵심이다. Postgres에서 `NULL = NULL`은 참이 아니라 NULL이라
평범한 UNIQUE 인덱스는 NULL이 낀 행을 전부 "서로 다르다"고 보고 통과시킨다. 그런데
`major_id = NULL`인 행이 79%이고 실제로 중복이 났던 간호학과 행도 NULL이었다 —
평범한 UNIQUE로는 그 사고를 못 막는다. 여기서 NULL은 "모름"이 아니라 "이 학과 전체에
공통 적용"이라는 확정적 의미이므로 의미상으로도 맞다.

## 반영 전 자동 검사

1. PostgreSQL 15+ 인가 (NULLS NOT DISTINCT 지원)
2. 기존 중복이 0인가 (있으면 인덱스 생성이 실패하므로 먼저 dedupe)
3. 이미 같은 인덱스가 있는가

## 사용법

    (venv) $ python scripts/apply_graduation_requirement_unique_index.py            # 검사만
    (venv) $ python scripts/apply_graduation_requirement_unique_index.py --commit
    (venv) $ python scripts/apply_graduation_requirement_unique_index.py --drop     # 되돌리기
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

INDEX_NAME = "uq_graduation_requirements_scope"
_CREATE = f"""
CREATE UNIQUE INDEX {INDEX_NAME}
    ON graduation_requirements (program_type, department_id, major_id, curriculum_year)
    NULLS NOT DISTINCT
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="실제로 인덱스를 만든다")
    ap.add_argument("--drop", action="store_true", help="인덱스를 제거한다 (롤백용)")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        from app.core.config import settings
        url = settings.DATABASE_URL

    engine = create_engine(url)
    with engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE tablename='graduation_requirements' AND indexname=:n"
        ), {"n": INDEX_NAME}).scalar() is not None

        if args.drop:
            if not exists:
                print(f"인덱스 {INDEX_NAME} 가 없다. 할 일 없음.")
                return 0
            conn.execute(text(f"DROP INDEX {INDEX_NAME}"))
            conn.commit()
            print(f"인덱스 {INDEX_NAME} 제거 완료.")
            return 0

        version = conn.execute(text("SHOW server_version")).scalar()
        major = int(str(version).split(".")[0])
        dup = conn.execute(text("""
            SELECT count(*) FROM (
              SELECT program_type, department_id, major_id, curriculum_year
              FROM graduation_requirements
              GROUP BY 1,2,3,4 HAVING count(*) > 1) t
        """)).scalar()

        print(f"PostgreSQL {version}  (NULLS NOT DISTINCT 필요: 15+)")
        print(f"기존 중복 조합: {dup}개")
        print(f"인덱스 존재: {exists}")

        problems = []
        if major < 15:
            problems.append(f"PostgreSQL {version}는 NULLS NOT DISTINCT를 지원하지 않는다 (15+ 필요)")
        if dup:
            problems.append(f"중복 {dup}개를 먼저 정리해야 한다 "
                            "(scripts/dedupe_graduation_requirements.py --commit)")
        if problems:
            print("\n반영 불가:")
            for p in problems:
                print("  -", p)
            return 1
        if exists:
            print("\n이미 반영돼 있다. 할 일 없음.")
            return 0

        if not args.commit:
            print("\n반영 가능한 상태다. 실제로 만들려면 --commit 을 붙여 다시 실행한다.")
            print("만들 인덱스:")
            print(_CREATE.strip())
            return 0

        conn.execute(text(_CREATE))
        conn.commit()
        print(f"\n인덱스 {INDEX_NAME} 생성 완료.")
        made = conn.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE indexname=:n"), {"n": INDEX_NAME}).scalar()
        print("  ", made)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""seeds/pnu_departments.json을 departments 테이블에 upsert한다.

pnu_departments.json은 onestop 수강편람 크롤러(ingestion/crawlers/
onestop_course_catalog.py)로 뽑은 학과/학부/전공명(MNG_DEPT_NM)에서
연구소/센터 같은 비학사 조직을 제외하고 만들었다. 새 학기에 학과가
바뀌면 크롤러를 다시 돌려 이 파일을 갱신한 뒤 이 스크립트를 재실행한다.

실행: python -m scripts.seed_departments
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.domains.academics.models import Department

SEED_PATH = Path(__file__).resolve().parent.parent / "seeds" / "pnu_departments.json"


def seed_departments() -> int:
    names = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        stmt = insert(Department).values([{"name": name} for name in names])
        stmt = stmt.on_conflict_do_nothing(index_elements=["name"])
        db.execute(stmt)
        db.commit()
    finally:
        db.close()
    return len(names)


if __name__ == "__main__":
    count = seed_departments()
    print(f"{count}개 학과/학부/전공 시드 완료")

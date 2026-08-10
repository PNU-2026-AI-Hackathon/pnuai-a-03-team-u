"""실계정 검증 — 균형교양 세부영역 반영 + 편입 인정 3학년 1학기 배치.

사용법:
    (venv) $ DATABASE_URL=... python scripts/verify_liberal_area_and_transfer.py <email>

  예: python scripts/verify_liberal_area_and_transfer.py blackest21@gmail.com

체크하는 것:
  1) student_course_records.category 값에 균형교양 7개 세부영역명이 들어가 있나?
     (portal-sync가 One-Stop 판정을 반영했는지 확인)
  2) student_course_records에 semester='입학전성적' 행이 있으면, 해당 학생의
     CourseRoadmapItem 중 편입 인정분이 3학년 1학기로 매핑돼 있나?
     (sync_completed_courses_to_roadmap의 특수 케이스 확인)

읽기만 하고 아무것도 수정하지 않는다.
"""

from __future__ import annotations

import os
import sys
from collections import Counter

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.domains.academics.models import StudentCourseRecord
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem
from app.domains.planning.roadmap_chat import _BALANCED_LIBERAL_AREAS
from app.domains.users.models import User


def main(email: str) -> int:
    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url)
    with Session(engine) as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"[ERROR] {email} 계정을 찾을 수 없습니다.")
            return 1

        print(f"== {user.name} <{user.email}> (user_id={user.id}) ==\n")

        records = db.scalars(
            select(StudentCourseRecord).where(StudentCourseRecord.user_id == user.id)
        ).all()
        print(f"student_course_records: {len(records)}건")

        # (1) 균형교양 세부영역 카운트
        cat_counter = Counter((r.category or "(없음)") for r in records)
        area_present = {a: cat_counter.get(a, 0) for a in _BALANCED_LIBERAL_AREAS}
        area_hit = sum(1 for cnt in area_present.values() if cnt > 0)
        print(f"\n[1] 균형교양 세부영역 반영 상태")
        print(f"    이수기록에 나타난 세부영역: {area_hit}/7개")
        for area, cnt in area_present.items():
            mark = "✅" if cnt > 0 else "⬜"
            print(f"      {mark} {area}: {cnt}건")
        if area_hit == 0:
            print(f"    → 세부영역이 하나도 안 붙어있음. portal-sync 재실행이 필요하거나")
            print(f"      One-Stop general_education_area_completion 판정에 이수 rows가 없을 수 있음.")
        else:
            still_generic = cat_counter.get("교양선택", 0)
            print(f"    → 세부영역이 붙은 이수 rows: {sum(area_present.values())}건")
            print(f"    → 아직 '교양선택'인 rows: {still_generic}건 (미이수 또는 override 대상 아님)")

        # (2) 편입 인정 3-1 배치
        transfer_records = [r for r in records if (r.semester or "").strip() == "입학전성적"]
        print(f"\n[2] 편입/조기이수 인정 학점 배치")
        print(f"    입학전성적 이수기록: {len(transfer_records)}건")
        if not transfer_records:
            print(f"    → 편입 인정 학점 없음(일반 재학생). 이 검증은 편입생 계정에서만 유효.")
        else:
            for r in transfer_records[:5]:
                print(f"      - {r.raw_course_name} ({r.category}, {r.credits}학점, year={r.year})")
            if len(transfer_records) > 5:
                print(f"      ... 외 {len(transfer_records) - 5}건")

            roadmap = db.scalar(
                select(CourseRoadmap).where(CourseRoadmap.user_id == user.id).order_by(CourseRoadmap.id.desc()).limit(1)
            )
            if roadmap is None:
                print(f"    → 이 사용자의 로드맵이 없습니다. 로드맵 생성 후 다시 확인 필요.")
            else:
                # 편입 이수기록의 course_name 기준으로 로드맵 항목 찾기
                names = {r.raw_course_name for r in transfer_records}
                items = db.scalars(
                    select(CourseRoadmapItem).where(
                        CourseRoadmapItem.roadmap_id == roadmap.id,
                        CourseRoadmapItem.course_name.in_(names),
                    )
                ).all()
                # planned_grade/planned_semester 분포
                slot_counter = Counter((it.planned_grade, it.planned_semester) for it in items)
                print(f"    로드맵 항목 매칭 (roadmap_id={roadmap.id}): {len(items)}건")
                for (grade, sem), cnt in sorted(
                    slot_counter.items(), key=lambda kv: (kv[0][0] is None, kv[0][0] or 0, kv[0][1] or "")
                ):
                    ok = "✅" if (grade == 3 and sem == "1학기") else "⚠️"
                    print(f"      {ok} planned_grade={grade}, planned_semester={sem!r}: {cnt}건")
                misplaced = [it for it in items if not (it.planned_grade == 3 and it.planned_semester == "1학기")]
                if not items:
                    print(f"    → 편입 이수기록이 로드맵에 반영 안 됨. sync_completed_courses_to_roadmap 재호출 필요할 수 있음.")
                elif misplaced:
                    print(f"    → ⚠️  {len(misplaced)}건이 3-1이 아닌 슬롯에 있음. history.py 수정 이전에 만들어진 옛 항목일 가능성 (로드맵 재생성 시 정리됨).")
                else:
                    print(f"    → ✅ 편입 이수기록 전부 3학년 1학기 슬롯으로 정상 배치.")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python scripts/verify_liberal_area_and_transfer.py <email>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))

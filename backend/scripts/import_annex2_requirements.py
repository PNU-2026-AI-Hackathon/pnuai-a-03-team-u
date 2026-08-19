"""별표2(교육과정표 HWP)에서 읽은 영역별 졸업기준 학점을 `graduation_requirements`에 반영.

HWP는 앱 의존성에 없으므로 변환은 먼저 밖에서 한다:

    backend/.venv/bin/hwp5html --output /tmp/annex 2024교육과정표.hwp

그다음:

    python -m scripts.import_annex2_requirements \
        --xhtml /tmp/annex/index.xhtml --department "정보컴퓨터공학부" \
        --major "컴퓨터공학전공" --curriculum-year 2024          # dry-run
    ... --commit                                                  # 실제 반영

**기본은 dry-run이다.** `--commit` 없이는 아무것도 안 쓴다. 공유 Supabase를 직접
가리키는 `DATABASE_URL`을 쓰므로(CLAUDE.md), 로컬 Postgres에서 먼저 돌려보고
결과를 확인한 뒤 반영한다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.ingestion.parsers.annex2_curriculum import parse_annex2_file  # noqa: E402


def _resolve_scope(conn, department: str, major: str | None) -> tuple[int, int | None]:
    dept_id = conn.execute(
        text("select id from departments where name = :name"), {"name": department}
    ).scalar()
    if dept_id is None:
        raise SystemExit(f"학과를 찾을 수 없다: {department!r}")
    if not major:
        return dept_id, None
    major_id = conn.execute(
        text("select id from majors where department_id = :d and name = :n"),
        {"d": dept_id, "n": major},
    ).scalar()
    if major_id is None:
        raise SystemExit(f"전공을 찾을 수 없다: {department}/{major}")
    return dept_id, major_id


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xhtml", required=True, help="hwp5html로 변환한 index.xhtml 경로")
    ap.add_argument("--department", required=True)
    ap.add_argument("--major", default=None)
    ap.add_argument("--curriculum-year", required=True)
    ap.add_argument("--program-type", default="primary")
    ap.add_argument("--commit", action="store_true", help="실제로 DB에 쓴다 (기본은 dry-run)")
    args = ap.parse_args()

    credits = parse_annex2_file(args.xhtml)
    print(f"원문 학과 표기 : {credits.department_label}")
    print(f"파싱 결과      : {credits.as_columns()}")
    if not credits.sums_to_total():
        # 합계가 안 맞으면 표를 잘못 읽은 것이다. 조용히 넣으면 안 된다.
        raise SystemExit("하위 항목 합이 총계와 다르다 — 표를 잘못 읽었을 가능성이 크다")
    print("합계 검산      : OK")

    engine = create_engine(settings.DATABASE_URL)
    with engine.begin() as conn:
        print(f"대상 DB        : {conn.execute(text('select current_database()')).scalar()}")
        dept_id, major_id = _resolve_scope(conn, args.department, args.major)
        params = {
            "d": dept_id, "m": major_id,
            "p": args.program_type, "y": args.curriculum_year,
        }
        existing = conn.execute(text("""
            select id, required_major_required, required_major_elective, required_total_credits
            from graduation_requirements
            where department_id = :d and major_id is not distinct from :m
              and program_type = :p and curriculum_year = :y
        """), params).first()

        cols = credits.as_columns()
        if existing:
            print(f"기존 행 id={existing[0]}: 전공필수 {existing[1]} → {cols['required_major_required']}, "
                  f"전공선택 {existing[2]} → {cols['required_major_elective']}, "
                  f"총 {existing[3]} → {cols['required_total_credits']}")
            stmt = text("""
                update graduation_requirements set
                    required_total_credits = :required_total_credits,
                    required_major_foundation = :required_major_foundation,
                    required_major_required = :required_major_required,
                    required_major_elective = :required_major_elective,
                    required_general_required = :required_general_required,
                    required_general_elective = :required_general_elective,
                    required_free_elective = :required_free_elective,
                    updated_at = :now
                where id = :id
            """)
            payload = {**cols, "now": dt.datetime.now(dt.UTC), "id": existing[0]}
        else:
            print(f"신규 행 추가 (dept={dept_id}, major={major_id}, "
                  f"{args.program_type}, {args.curriculum_year})")
            stmt = text("""
                insert into graduation_requirements
                    (department_id, major_id, program_type, curriculum_year,
                     required_total_credits, required_major_foundation, required_major_required,
                     required_major_elective, required_general_required, required_general_elective,
                     required_free_elective, created_at, updated_at)
                values
                    (:d, :m, :p, :y,
                     :required_total_credits, :required_major_foundation, :required_major_required,
                     :required_major_elective, :required_general_required, :required_general_elective,
                     :required_free_elective, :now, :now)
            """)
            payload = {**cols, **params, "now": dt.datetime.now(dt.UTC)}

        if not args.commit:
            print("\n[dry-run] --commit 을 붙이면 위 내용을 반영한다.")
            conn.rollback()
            return
        conn.execute(stmt, payload)
        print("\n반영 완료.")


if __name__ == "__main__":
    main()

"""SW융합 프로그램(융합트랙 14 + 연계전공 5 + 융합전공 1)의 special_rules 자동 백필

Dowon PR #99가 `program_courses`에 20개 프로그램의 인정 과목을 라벨(예:
"학과전공과목(택1-A)", "SW융합공통교과목(택2)")과 함께 저장했지만 판정 규칙
(`special_rules` JSONB)은 미채움. 이 스크립트는 requirement_group 라벨을 파싱해
`graduation_requirements.special_rules`를 자동 생성한다.

**라벨 파싱 규칙:**
- `"(필수)"` → `{type: "all"}`
- `"(택N-X)"` → `{type: "min_courses", n: N}` (X는 그룹 세분)
- `"(택N)"` → `{type: "min_courses", n: N}`
- 접미사 없음(예: "학과전공과목" 단독) → `{type: "min_credits", min_credits: ?}` 로 처리
  (구체 학점은 seed_sw_convergence_programs.py의 rule 문자열 참고 필요, 여기선 skip)

사용:
    ./backend/.venv/bin/python -m scripts.backfill_sw_convergence_rules
    ./backend/.venv/bin/python -m scripts.backfill_sw_convergence_rules --apply
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import (
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
)


# 라벨 파싱: "학과전공과목(택1-A)" → base="학과전공과목", suffix="택1-A"
LABEL_RE = re.compile(r"^(?P<base>[^(]+?)(?:\((?P<suffix>[^)]+)\))?$")

# 접미사 패턴: "택N-X" or "택N" or "필수"
CHOOSE_RE = re.compile(r"^택(?P<n>\d+)(?:-(?P<group>[A-Z0-9]+))?$")


def parse_label(label: str) -> tuple[str, dict]:
    """라벨 → (canonical_label, rule_dict)."""
    m = LABEL_RE.match(label.strip())
    if not m:
        return label, {"label": label, "type": "unknown"}
    base = m.group("base").strip()
    suffix = (m.group("suffix") or "").strip()
    if suffix == "필수":
        return f"{base}(필수)", {"label": f"{base}(필수)", "type": "all"}
    cm = CHOOSE_RE.match(suffix) if suffix else None
    if cm:
        n = int(cm.group("n"))
        grp = cm.group("group") or ""
        canon = f"{base}(택{n}{('-' + grp) if grp else ''})"
        return canon, {"label": canon, "type": "min_courses", "n": n}
    # 접미사 없음 or 알 수 없음 — 그룹 전체 이수 대상(all)로 우선 처리
    if not suffix:
        return base, {"label": base, "type": "all"}
    return f"{base}({suffix})", {"label": f"{base}({suffix})", "type": "unknown"}


def build_rules_for_program(courses: list[ProgramCourse]) -> dict:
    """program_courses 리스트 → special_rules dict."""
    label_groups: dict[str, list] = defaultdict(list)
    for c in courses:
        canon, rule = parse_label(c.requirement_group or "")
        label_groups[canon].append((c, rule))
    groups = []
    seen = set()
    for canon, items in label_groups.items():
        if canon in seen:
            continue
        seen.add(canon)
        rule = items[0][1]
        groups.append(rule)
    return {"groups": groups, "notes": "SW융합 라벨 자동 파싱 (backfill)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    dry = not args.apply

    db = SessionLocal()
    try:
        # (department_id, major_id, curriculum_year) 기준으로 program_courses 그룹핑
        rows = db.execute(select(ProgramCourse)).scalars().all()
        by_program: dict[tuple, list] = defaultdict(list)
        for pc in rows:
            key = (pc.department_id, pc.major_id, pc.curriculum_year)
            by_program[key].append(pc)

        print(f"총 {len(by_program)}개 프로그램 (department_id, major_id, curriculum_year)\n")

        upsert_count = 0
        update_count = 0
        skip_count = 0
        for (dept_id, major_id, curr_year), cs in sorted(by_program.items()):
            dept = db.get(Department, dept_id)
            major = db.get(Major, major_id) if major_id else None
            special = build_rules_for_program(cs)
            program_label = f"{dept.name if dept else '?'}/{major.name if major else '(dept)'}@{curr_year or '-'}"

            q = select(GraduationRequirement).where(
                GraduationRequirement.department_id == dept_id,
                GraduationRequirement.major_id == major_id,
                GraduationRequirement.program_type == "interdisciplinary",
                GraduationRequirement.curriculum_year == curr_year,
            )
            existing = db.execute(q).scalar_one_or_none()
            if existing:
                if existing.special_rules == special:
                    action = "unchanged"
                    skip_count += 1
                else:
                    action = "update"
                    update_count += 1
                    if not dry:
                        existing.special_rules = special
            else:
                action = "insert"
                upsert_count += 1
                if not dry:
                    db.add(GraduationRequirement(
                        department_id=dept_id,
                        major_id=major_id,
                        program_type="interdisciplinary",
                        curriculum_year=curr_year,
                        special_rules=special,
                    ))
            n_groups = len(special.get('groups', []))
            print(f"  [{action:9s}] {program_label:60s} groups={n_groups} courses={len(cs)}")

        if dry:
            db.rollback()
            print(f"\n[DRY-RUN] insert={upsert_count} update={update_count} unchanged={skip_count}")
        else:
            db.commit()
            print(f"\n[COMMITTED] insert={upsert_count} update={update_count} unchanged={skip_count}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

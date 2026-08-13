"""AI융합트랙(SW융합트랙) 14개의 special_rules 정정 + 성격 명시.

배경 (2026-08-11):
  DB의 interdisciplinary program_type엔 3종류가 섞여 있다:
    (a) SW연계전공 5개 (48학점, 정식 다전공): 임베디드SW·에너지IoT 등
    (b) 융합전공 1개 (42학점, 정식 다전공): 핀테크융합전공
    (c) SW융합트랙 14개 (21학점, **졸업요건 아님**): 인증형 트랙

  (c)는 "졸업증명서에 이수 과정명 표기"되는 인증(certification)이지 졸업요건이
  아니다. 학과전공 12~15학점 + AI융합공통 6~9학점 = 총 21학점.

  기존 시드에선 (c)도 (a)/(b)와 동일하게 required_total_credits + all-필수 그룹
  구조로만 들어가 있어 챗이 "이수 필수 요건"으로 오해할 여지가 있다.

fix:
  14개 트랙의 special_rules에 아래 필드 추가 —
    - certification_type: "AI융합트랙"
    - not_graduation_requirement: True
    - dept_credits, ai_common_credits: 학점 breakdown
    - source: 공식 안내 URL

  이 필드로 판정·프롬프트가 트랙을 "옵션 이수"로 다룰 수 있다.

출처: https://ai.pusan.ac.kr (AI융합교육원 - AI융합트랙, 2026.03.01 기준)

사용법:
    DATABASE_URL=... python -m scripts.seed_ai_convergence_tracks_2026_08_11
        [--apply]
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import GraduationRequirement
# FK 대상
from app.domains.users.models import User  # noqa: F401


# (dept_id, major_id, dept_credits_range, ai_common_credits_range)
# range는 tuple(min, max). 두 값이 같으면 단일 값.
_TRACKS: list[tuple[int, int, tuple[int, int], tuple[int, int]]] = [
    # dept, major, dept_credits, ai_common_credits
    (20, 68, (12, 15), (6, 9)),   # 행정학과 · DMS(행정관리과학)
    (19, 67, (12, 12), (9, 9)),   # 정치외교학과 · 정치데이터사이언스
    (16, 64, (15, 15), (6, 6)),   # 사회복지학과 · 데이터사이언스와복지
    (17, 65, (15, 15), (6, 6)),   # 사회학과 · 소셜데이터사이언스
    (18, 66, (15, 15), (6, 6)),   # 심리학과 · 심리데이터사이언스
    (14, 82, (12, 15), (6, 9)),   # 문헌정보학과 · 문헌정보데이터분석
    (15, 63, (15, 15), (6, 6)),   # 미디어커뮤니케이션학과 · 미디어데이터사이언스
    (40, 74, (15, 15), (6, 6)),   # 산업공학과 · 산업AI
    (104, 69, (15, 15), (6, 6)),  # 공공정책학부 · 공공데이터분석
    (102, 70, (12, 12), (9, 9)),  # 의류학과 · 디지털패션
    (98, 71, (15, 15), (6, 6)),   # 스포츠과학과 · AI 스포츠과학
    (75, 72, (15, 15), (6, 6)),   # 디자인학과 · 디자인컴퓨팅
    (1, 73, (12, 15), (6, 9)),    # 의생명융합공학부 · 바이오메디컬디바이스&데이터
    (94, 75, (15, 15), (6, 6)),   # 조경학과 · 도시·환경·생태 데이터분석
]

SOURCE_URL = "https://ai.pusan.ac.kr"


def _build_special(dept_credits: tuple[int, int], ai_credits: tuple[int, int]) -> dict:
    dc_str = f"{dept_credits[0]}" if dept_credits[0] == dept_credits[1] else f"{dept_credits[0]}~{dept_credits[1]}"
    ac_str = f"{ai_credits[0]}" if ai_credits[0] == ai_credits[1] else f"{ai_credits[0]}~{ai_credits[1]}"
    return {
        "certification_type": "AI융합트랙",
        "not_graduation_requirement": True,
        "notes": (
            f"AI융합교육원(소프트웨어융합교육원) 운영 트랙 인증. 이수 시 졸업증명서에 "
            f"이수 과정명 표기. 학과전공 {dc_str}학점 + AI융합 공통교과목 {ac_str}학점 = 총 21학점. "
            "졸업요건 아님, 학생이 선택적으로 이수."
        ),
        "total_credits": 21,
        "dept_credits": {"min": dept_credits[0], "max": dept_credits[1]},
        "ai_common_credits": {"min": ai_credits[0], "max": ai_credits[1]},
        "source": SOURCE_URL,
        "groups": [
            {
                "type": "min_credits",
                "label": "학과전공과목",
                "required_credits": dept_credits[0],
                "notes": f"학과 개설 전공과목 중 {dc_str}학점.",
            },
            {
                "type": "min_credits",
                "label": "AI융합 공통교과목",
                "required_credits": ai_credits[0],
                "notes": f"AI융합교육원 개설 공통 교과목 {ac_str}학점.",
            },
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    dry_run = not args.apply

    db = SessionLocal()
    stats = {"update": 0, "unchanged": 0, "missing": []}
    try:
        for dept_id, major_id, dc, ac in _TRACKS:
            gr = db.scalars(
                select(GraduationRequirement).where(
                    GraduationRequirement.department_id == dept_id,
                    GraduationRequirement.major_id == major_id,
                    GraduationRequirement.program_type == "interdisciplinary",
                )
            ).first()
            if gr is None:
                stats["missing"].append(f"dept={dept_id} major={major_id}")
                continue
            new_special = _build_special(dc, ac)
            if gr.special_rules == new_special and gr.required_total_credits == 21:
                stats["unchanged"] += 1
                continue
            stats["update"] += 1
            print(f"  [update] dept={dept_id} major={major_id}")
            if not dry_run:
                gr.special_rules = new_special
                gr.required_total_credits = 21

        print(f"\n[summary] update={stats['update']} unchanged={stats['unchanged']} missing={len(stats['missing'])}")
        if stats["missing"]:
            print("  missing:", stats["missing"])

        if dry_run:
            db.rollback()
            print("🔍 [dry-run] --apply로 반영.")
        else:
            db.commit()
            print("✅ [committed] 반영 완료.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

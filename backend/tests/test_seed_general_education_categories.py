"""교양 세부영역 이수구분이 학과 1행 때문에 통째로 뒤집히는 사고 회귀 테스트.

## 왜 이 테스트가 있는가 — 2026-08-20에 실제로 있었던 사고

교양 세부영역(`효원균형교양` 6개 / `효원창의교양` 3개)은 `courses`에 `ZFz` placeholder 한
행씩으로 들어간다. `scripts/import_courses_from_ais.py`는 교양 행을 전학교 공통으로 보고
**course_code 기준으로 한 행만 남긴다** — `seen_ge`에 이미 있으면 그냥 `continue`. 즉 CSV에서
**먼저 나온 행이 조용히 이긴다.**

`seeds/ais_courses_2026.csv`(AIS 스냅샷 그대로)에는 학과별 교육과정표 행이 학과 수만큼
반복되는데, 세 영역에서 각각 딱 1행씩 이수구분이 어긋나 있었다:

    ZFz000098 효원브릿지       효원균형교양 58행 / 효원핵심교양 1행 (국어국문학과)
    ZFz000092 사회와문화       효원균형교양 98행 / 효원핵심교양 1행 (원예생명과학과)
    ZFz000110 인성과 사회봉사  효원창의교양 95행 / 효원균형교양 1행 (한국음악학과)

그 중 `ZFz000098`은 소수값 행이 CSV 앞쪽(국어국문학과, 67행)에 있어서 실제로 이겼다 —
Supabase `courses`에 `효원브릿지`가 **효원핵심교양**으로 들어가 있었다. 나머지 둘이 다수값으로
들어간 건 실력이 아니라 행 순서 운이다. 영역 하나가 엉뚱한 그룹에 들어가면
"효원균형교양 6개 소영역 중 N개" 같은 판정이 그 영역째로 어긋난다.

## 왜 소수 1행이 학과 정책이 아니라 오류인가

교육과정 편성 및 운영규정(260225 개정) 제9조:

    ① 효원핵심교양 교과목은 다음 각 호와 같이 편성한다.
       열린사고와 표현 / 대학영어 / 인공지능과 디지털사고 / 고전읽기와 토론 / 공학작문 및 발표
    ② 효원균형교양 교과목은 다음 각 호와 같이 6개 소영역으로 구분한다.
       사상과 역사 / 사회와 문화 / 문학과 예술 / 과학과 기술 / 세계와 소통 / 효원브릿지
    ③ 효원창의교양 교과목은 다음 각 호와 같이 3개 소영역으로 구분한다.
       융합과 창의 / 건강과 레포츠 / 인성과 사회봉사

효원핵심교양은 **과목명으로 닫힌 목록**이라 애초에 "영역"이 들어갈 자리가 없고, 소영역이 어느
그룹인지는 전교 공통으로 규정이 정한다. 제11조가 학과에 맡기는 것은 이수학점과 "몇 개
소영역을 이수할지"이지 "그 영역이 어느 그룹인지"가 아니다. 학과는 **어느 영역을 자기
교육과정표에 넣을지**를 고를 뿐이다(99개 학과 중 효원브릿지를 넣은 곳은 59개뿐).

## 기초교양은 예외 — 학과별로 갈리는 게 정상이다

제11조⑪: "기초교양 교과목은 … 다른 학과에서 편성한 효원균형교양 및 효원창의교양 교과목 중
전공과 연계하여 6학점 범위 안에서 편성할 수 있다." 즉 `기초교양`은 과목의 성질이 아니라
학과가 덧씌우는 지정이다. `ZF1200703 브릿지기초물리(I)`가 어떤 학과엔 `기초교양`, 어떤
학과엔 `효원균형교양`인 것은 원본이 맞다. 이 테스트가 그걸 실패로 잡으면 안 된다.
"""

import csv
from pathlib import Path

from scripts.import_courses_from_ais import find_general_education_category_conflicts

SEED_CSV = Path(__file__).resolve().parent.parent / "seeds" / "ais_courses_2026.csv"

# 규정 제9조②③ 기준 정답. 2026-08-20에 AIS 스냅샷에서 각각 1행씩 어긋나 있던 것들이다.
EXPECTED_AREA_CATEGORIES = {
    "ZFz000091": "효원균형교양",  # 사상과역사
    "ZFz000092": "효원균형교양",  # 사회와문화  ← 원예생명과학과 1행이 효원핵심교양이었다
    "ZFz000093": "효원균형교양",  # 문학과예술
    "ZFz000094": "효원균형교양",  # 과학과기술
    "ZFz000096": "효원균형교양",  # 세계와 소통
    "ZFz000098": "효원균형교양",  # 효원브릿지  ← 국어국문학과 1행이 효원핵심교양이었다
    "ZFz000095": "효원창의교양",  # 건강과레포츠
    "ZFz000097": "효원창의교양",  # 융합과 창의
    "ZFz000110": "효원창의교양",  # 인성과 사회봉사 ← 한국음악학과 1행이 효원균형교양이었다
}


def _seed_rows() -> list[dict]:
    with SEED_CSV.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_no_general_education_group_conflict_in_seed():
    """같은 교양 course_code에 효원핵심/균형/창의가 섞여 있으면 안 된다."""
    conflicts = [
        c
        for c in find_general_education_category_conflicts(_seed_rows())
        if c["kind"] == "group_conflict"
    ]
    assert conflicts == [], (
        "같은 교양 과목코드에 이수구분이 갈려 있다. 적재 시 CSV에서 먼저 나온 행이 이기므로 "
        "DB 값이 행 순서에 좌우된다:\n"
        + "\n".join(f"  - {c['course_code']} {c['course_name']}: {c['counts']}" for c in conflicts)
    )


def test_liberal_area_placeholders_match_regulation():
    """ZFz 영역 placeholder는 규정 제9조②③이 정한 그룹에 있어야 한다 (전 행)."""
    wrong = [
        f"{r['ais_dept_code']} {r['unit_name']}: {r['course_code']} {r['course_name']} "
        f"→ {r['category']} (기대 {EXPECTED_AREA_CATEGORIES[r['course_code']]})"
        for r in _seed_rows()
        if r["course_code"] in EXPECTED_AREA_CATEGORIES
        and r["category"].strip() != EXPECTED_AREA_CATEGORIES[r["course_code"]]
    ]
    assert wrong == [], "교양 세부영역이 규정과 다른 이수구분으로 들어간 행:\n" + "\n".join(
        f"  - {w}" for w in wrong
    )


def test_기초교양_overlay_is_not_a_conflict():
    """기초교양은 학과 지정이라 같은 과목이 학과별로 갈리는 게 정상 — 실패로 잡으면 안 된다."""
    rows = [
        {"ais_dept_code": "1", "unit_name": "가학과", "category": "기초교양",
         "course_code": "ZF1200703", "course_name": "브릿지기초물리(I)"},
        {"ais_dept_code": "2", "unit_name": "나학과", "category": "효원균형교양",
         "course_code": "ZF1200703", "course_name": "브릿지기초물리(I)"},
    ]
    kinds = [c["kind"] for c in find_general_education_category_conflicts(rows)]
    assert kinds == ["기초교양_overlay"]


def test_group_conflict_is_detected():
    """검사가 실제로 걸러내는지 — 2026-08-20 사고 그대로 재현."""
    rows = [
        {"ais_dept_code": "311100", "unit_name": "국어국문학과", "category": "효원핵심교양",
         "course_code": "ZFz000098", "course_name": "효원브릿지"},
        {"ais_dept_code": "311200", "unit_name": "다른학과", "category": "효원균형교양",
         "course_code": "ZFz000098", "course_name": "효원브릿지"},
        {"ais_dept_code": "311300", "unit_name": "또다른학과", "category": "효원균형교양",
         "course_code": "ZFz000098", "course_name": "효원브릿지"},
    ]
    (conflict,) = find_general_education_category_conflicts(rows)
    assert conflict["kind"] == "group_conflict"
    assert conflict["majority"] == "효원균형교양"
    assert conflict["tied"] is False
    assert conflict["minority_units"] == {"효원핵심교양": ["국어국문학과"]}

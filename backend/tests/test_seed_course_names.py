"""과목명 접미사(로마숫자) 유실 회귀 테스트.

## 왜 이 테스트가 있는가 — 2026-07-23에 실제로 있었던 사고

PR #92(8c76dd3)에서 컴퓨터공학전공 커리큘럼 58행을 `seeds/ais_courses_2026.csv`에 **손으로
append**하면서 AIS 원문의 로마숫자 접미사가 4행에서 빠졌다.

    원문(raw_data/draft_curriculum_table_2026-07-06.csv)   시드에 들어간 값
    CB1501027 이산수학(I)    / CB2001104 이산수학(II)   →  둘 다 "이산수학"
    CB1501005 일반물리학(I)  / CB1501009 일반물리학(II)  →  둘 다 "일반물리학"

그 CSV로 2026-07-22에 적재된 `courses` 4행이 **서로 다른 과목인데 같은 이름**이 됐다.
`timetable_chat._sibling_course_ids`는 (과목명·학과·전공·이수구분·학점)이 같은 행을 "같은
과목의 형제"로 묶어 개설을 합치는데, 일반물리학 두 행은 다섯 값이 전부 같아져서 (I)의
분반(0개)과 (II)의 분반(2개, 2026-2학기)이 한 덩어리로 보였다. 이수 완료 제외
(`timetable._completed_course_norms`)도 과목명 정규화 비교라 전적 원문 "일반물리학(I)"이
DB의 "일반물리학"과 안 맞아 어긋난다.

**정상 중복과 구분하는 기준**: 부산대는 같은 과목명에 개설 주체별로 다른 교과목코드를
발급한다(교과목코드 앞 2글자 = 개설 주체). 접두사가 다르면 원본 데이터의 정상 성질이므로
합치면 안 되고(예: 약학과 401300 `약리학(I)` DS2002822/PD2002822), 여기서도 통과시킨다.
**접두사까지 같은데 과목명이 겹치면** 접미사 유실이다.
"""

import csv
from pathlib import Path

from scripts.import_courses_from_ais import find_suffix_dropped_collisions

SEED_CSV = Path(__file__).resolve().parent.parent / "seeds" / "ais_courses_2026.csv"

# AIS 원문 기준 정답. 2026-07-23 수기 append에서 잘못 들어갔던 값들이다.
# PR #92의 수기 append에서 원문과 달라진 7행 전부. 로마숫자 접미사 유실 4건과
# 공백 혼입 3건이 같은 커밋에서 함께 들어왔다 — 공백 쪽은 이름이 서로 달라져
# 동명 충돌 검사에 안 걸리므로, 값 자체를 여기서 고정해야 한다(독립 리뷰 지적:
# 공백 3행을 되돌려도 4건이 전부 통과했다).
EXPECTED_NAMES = {
    "CB1501027": "이산수학(I)",
    "CB2001104": "이산수학(II)",
    "CB1501005": "일반물리학(I)",
    "CB1501009": "일반물리학(II)",
    "CB1501014": "C++프로그래밍과실습",
    "CB2001103": "AI프로그래밍",
    "CB2001611": "지능형IoT플랫폼",
}


def _seed_rows() -> list[dict]:
    with SEED_CSV.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_seed_has_no_suffix_dropped_collisions():
    """같은 단위·같은 개설 주체에 동명 과목이 있으면 접미사가 빠진 것이다."""
    collisions = find_suffix_dropped_collisions(_seed_rows())
    assert collisions == [], (
        "과목명 접미사(I/II 등)가 빠진 것으로 의심되는 행이 있다. AIS 원문을 다시 확인하라:\n"
        + "\n".join(f"  - {c}" for c in collisions)
    )


def test_seed_keeps_roman_suffix_for_known_cases():
    """실제로 잘렸던 4개 과목의 이름을 고정한다 (다시 잘리면 여기서 잡힌다)."""
    by_code = {r["course_code"].strip(): r["course_name"] for r in _seed_rows()}
    for code, expected in EXPECTED_NAMES.items():
        assert by_code.get(code) == expected, f"{code}: {by_code.get(code)!r} != {expected!r}"


def test_different_owner_prefix_is_not_a_collision():
    """개설 주체가 다른 동명 과목은 원본 데이터의 정상 성질 — 잡으면 안 된다."""
    rows = [
        {"ais_dept_code": "401300", "course_name": "약리학(I)", "course_code": "DS2002822"},
        {"ais_dept_code": "401300", "course_name": "약리학(I)", "course_code": "PD2002822"},
    ]
    assert find_suffix_dropped_collisions(rows) == []


def test_same_owner_prefix_collision_is_detected():
    """사고 당시 시드 상태를 재현하면 검출돼야 한다."""
    rows = [
        {"ais_dept_code": "594001", "course_name": "이산수학", "course_code": "CB1501027"},
        {"ais_dept_code": "594001", "course_name": "이산수학", "course_code": "CB2001104"},
    ]
    found = find_suffix_dropped_collisions(rows)
    assert len(found) == 1 and "이산수학" in found[0]


def test_적재_함수가_충돌_발견_시_실제로_중단한다():
    """**가드 배선.** 순수 함수만 테스트하면 그게 importer에 연결됐는지는 아무도 안 본다.

    독립 리뷰(2026-08-20)가 잡았다 — `if collisions and not allow_name_collisions:`를
    `if False:`로 바꿔도 4건이 전부 통과했다. #187·#188에서도 같은 형태의 결함이
    나왔다(함수는 테스트하면서 호출부는 안 함).

    실제 적재(DB 쓰기)까지 가지 않고, 충돌이 있으면 **DB에 손대기 전에** SystemExit이
    나는지만 본다 — 가드가 `SessionLocal()` 앞에 있어야 한다는 계약이기도 하다.
    """
    import csv as _csv
    import tempfile
    from pathlib import Path

    from scripts import import_courses_from_ais as importer

    # 같은 단위·같은 개설 주체에 동명 과목 2행 = 접미사 유실 상황
    rows = [
        {"ais_dept_code": "594001", "unit_name": "테스트학부", "curriculum_year": "2026",
         "grade": "1학년", "semester": "1학기", "category": "전공기초",
         "course_name": "이산수학", "course_code": "CB1501027", "credits": "3.0"},
        {"ais_dept_code": "594001", "unit_name": "테스트학부", "curriculum_year": "2026",
         "grade": "2학년", "semester": "2학기", "category": "전공선택",
         "course_name": "이산수학", "course_code": "CB2001104", "credits": "3.0"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "seed.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

        try:
            # **dry_run=True 필수.** 가드가 깨진 회귀 상황에서는 이 호출이 `SessionLocal()`
            # 너머로 진입하는데, `config.py`의 `env_file=".env"` 때문에 메인 트리에서 그냥
            # pytest를 돌리면 DATABASE_URL이 **팀 공유 Supabase**다. 그러면 이 테스트가
            # CB1501027/CB2001104의 이름을 `이산수학`으로 되돌리고 commit해서 —
            # **자기가 지키려던 데이터를 자기가 깬다**(독립 리뷰 지적).
            # dry_run이어도 가드가 없으면 SystemExit이 안 나므로 계약 검증은 그대로다.
            importer.import_courses(
                courses_csv=csv_path,
                mapping_path=importer.DEFAULT_MAPPING,
                dry_run=True,
            )
        except SystemExit as exc:
            assert exc.code == 1, f"충돌인데 종료코드가 {exc.code}"
        else:
            raise AssertionError(
                "충돌이 있는데 적재가 그대로 진행됐다 — 가드가 importer에 연결되지 않았다."
            )

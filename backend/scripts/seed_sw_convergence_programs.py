"""SW융합교육과정(융합트랙·연계전공·융합전공)을 계층과 졸업요건에 적재한다.

출처: 「PNU SW융합교육과정 안내」 p.2~4 (부산대학교 교육과정 편성 및 운영규정
제23조의4·제24조의4, 24.04.01. 개정 기준)

모델링 결정
-----------
- 프로그램 하나 = 개설학과 밑의 `majors` 행. 같은 프로그램명이라도 개설학과가
  다르면 다른 행이다. `graduation_requirements`/`user_academic_programs`가 이미
  (department_id, major_id, program_type)로 키를 잡고 있어, 학과별로 다른 이수학점을
  추가 스키마 없이 표현할 수 있다.
- `program_type`은 전부 `interdisciplinary` 하나로 통합한다. 프로그램 식별은
  major_id가 이미 하므로 유형별로 값을 나눌 실익이 없고, 유형 구분은 majors.name의
  접미사("(SW융합트랙)" 등)로 남긴다.
- 개설 주체가 세부전공인 경우(디자인앤테크놀로지전공, 전자공학전공, 전기공학전공)는
  majors가 department를 부모로만 가질 수 있어 **상위 학과 밑에 붙인다.** 어느 세부전공이
  운영하는지는 HOST_MAJOR_NOTE에 기록만 해둔다.

범위에서 제외한 것
------------------
- **SW융합마이크로디그리**: 자료상 "25학년도 2학기 이후 신설 예정"이라 확정 편제가 아님.
- **부전공/복수전공**: SW학과 과목을 이수하는 형태라 별도 프로그램 행이 필요 없다.

인정 과목(TRACK_COURSES)
------------------------
자료의 트랙별 교육과정표를 `program_courses`에 넣는다. 교과목번호(course_code)로
매칭하고, 매칭 실패는 조용히 넘기지 않고 건너뜀 목록에 남긴다 — 이름으로 매칭하면
같은 이름의 다른 과목에 잘못 붙을 수 있어서다(실제로 자료의 '도서관데이터분석실습'은
LI2001637이 아니라 LI2001639이고, LI2001637은 현행 '디지털자료관리'다).

**아직 반영하지 못한 것**: "해당 과목 중 최소 4과목 이상", "공통교과목 중 최소 2과목"
같은 과목 수 조건. flat `graduation_requirements`는 이수구분별 학점 합계만 담는
구조라 표현할 수 없다. 아래 min_courses에 데이터로만 적어두고, 나머지 트랙 자료를
모두 받은 뒤 그룹 요건 스키마를 한 번에 설계한다.

이수학점 근거
-------------
- SW융합트랙: 학과전공과목(12~15) + SW융합 공통교과목(6~9) = **총 21학점**
- SW연계전공: 최소전공인정학점인 전공필수 및 전공선택 **48학점**
- SW융합전공: "복수전공 이수 시 해당 전공의 최소전공 학점" — 전공별로 달라 자료에
  확정 숫자가 없다. required_total_credits를 NULL로 두고 요건 계산에서 경고가 뜨게 한다.

flat `graduation_requirements`는 이수구분별 컬럼(전공필수/전공선택/교양…)만 있는데
위 기준은 "학과전공 + SW공통"처럼 다른 축으로 쪼개져 있어 매핑되지 않는다. 그래서
총학점만 채우고 이수구분 컬럼은 비운다.

실행:
    python -m scripts.seed_sw_convergence_programs             # dry-run
    python -m scripts.seed_sw_convergence_programs --apply     # 실제 반영
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
    School,
)
from app.domains.courses.models import Course

CURRICULUM_YEAR = "2026"
PROGRAM_TYPE = "interdisciplinary"

TRACK_SUFFIX = "(SW융합트랙)"
LINKED_SUFFIX = "(SW연계전공)"
CONVERGENCE_SUFFIX = "(SW융합전공)"

TRACK_TOTAL_CREDITS = 21
LINKED_TOTAL_CREDITS = 48

# 적재에서 뺄 트랙이 생기면 여기에 이름을 넣는다.
_EXCLUDED_TRACKS: set[str] = set()

# 이수 기준상의 묶음. flat graduation_requirements의 이수구분(전공필수/교양…)과는
# 다른 축이라 program_courses.requirement_group에 담는다.
GROUP_DEPARTMENT_MAJOR = "학과전공과목"
GROUP_SW_COMMON = "SW융합공통교과목"

# SW융합 공통교과목 개설 주체. AIS 2026 시드는 학과 편제 기준이라 학과가 아닌
# 소프트웨어융합교육원 개설 과목이 통째로 빠져 있다(SF 접두 과목 0건). 공통교과목은
# 모든 트랙의 요건(6~9학점)에 걸리므로 여기서 개설 주체와 과목을 함께 만든다.
# 학위를 주는 학과가 아니므로 회원가입 학과 선택 목록에서는 제외한다
# (app/api/departments.py의 NON_DEGREE_DEPARTMENTS).
SW_COMMON_COLLEGE = "소프트웨어융합교육원"
SW_COMMON_DEPARTMENT = "소프트웨어융합교육원"

# 자료에 나온 SW융합 공통교과목. 전부 3학점, 학년·학기 무관, 이수구분 '일선'.
# courses에 없으면 만들고, 있으면 그대로 쓴다.
SW_COMMON_COURSE_DEFS = [
    ("SF1101073", "데이터분석입문"),
    ("SF1101074", "AI이해를위한파이썬기초"),
    ("SF1101080", "AI리터러시의이해"),
    ("SF1101081", "메타버스활용프로젝트"),
    ("SF1101082", "창의적프로그래밍"),
    ("SF1101083", "데이터마이닝"),
    ("SF1101084", "데이터리터러시의이해"),
    ("SF1101085", "인공지능기초수학"),
]
# 연계전공 4개가 공통으로 전공선택에 넣는 소프트웨어융합교육원 개설 과목.
# 위 SW융합공통교과목(SF11010xx)과는 별개 과목군이고 계절학기에만 열린다.
SW_FOUNDATION_COURSE_DEFS = [
    ("ES1200313", "소프트웨어융합기초(I)"),
    ("ES1200338", "소프트웨어융합기초(II)"),
    ("ES1200427", "소프트웨어융합기초(III)"),
    ("ES1200634", "소프트웨어융합기초(IV)"),
]
SW_FOUNDATION_SEMESTER = "여름계절수업"

# AIS 2026 시드에 없어서 자료(교육과정표) 기준으로 직접 만드는 과목.
# (교과목번호, 교과목명, 개설학과, 세부전공 or None, 이수구분, 학점, 학년, 학기, 사유)
#
# **두 종류가 섞여 있으니 나중에 반드시 구분해서 재검토할 것.**
#  (a) 시드 누락이 명백한 것 — 디자인앤테크놀로지전공은 과목이 0건인데 같은 학과의
#      애니메이션전공 32건·시각디자인전공 39건은 정상이다. 컴퓨터그래픽스·피지컬컴퓨팅·
#      HCI는 다른 학과에는 실재해서 개설 자체는 확실하다.
#  (b) 폐지·개편 가능성이 있는 것 — 소속 학과가 정상 시드된 상태에서 전체 DB 어디에도
#      없다(스포츠과학과 53과목, 산업공학과 61과목, 의생명융합공학부 84과목 모두 정상).
#      자료가 구버전 코드를 여럿 갖고 있었던 점을 감안하면 2026 교육과정에서 빠졌을 수 있다.
#      **이 과목들은 실제로 개설되지 않을 수 있고, 그러면 AI 로드맵이 수강 불가능한 과목을
#      추천하게 된다.** 학사 확인 후 미개설로 판명되면 아래 목록에서 지우고
#      program_courses의 해당 행도 함께 정리해야 한다.
MISSING_COURSE_DEFS = [
    # (a) 디자인앤테크놀로지전공 — 시드 누락
    ("VF3500076", "컴퓨터그래픽스", "디자인학과", "디자인앤테크놀로지전공", "전공필수", 3.0, "2", "2", "seed-gap"),
    ("VF3500077", "피지컬컴퓨팅", "디자인학과", "디자인앤테크놀로지전공", "전공필수", 3.0, "3", "1", "seed-gap"),
    ("VF3500072", "키네틱타이포그래피", "디자인학과", "디자인앤테크놀로지전공", "전공필수", 3.0, "3", "1", "seed-gap"),
    ("VF3600180", "HCI", "디자인학과", "디자인앤테크놀로지전공", "전공필수", 3.0, "3", "2", "seed-gap"),
    ("VF3500081", "컴퓨터비전", "디자인학과", "디자인앤테크놀로지전공", "전공선택", 3.0, "3", "2", "seed-gap"),
    # (b) 폐지·개편 가능성 있음 — 학사 확인 필요
    ("SC3600515", "스폰서십마케팅", "스포츠과학과", None, "전공선택", 3.0, "4", "2", "unverified"),
    ("SC3300968", "스포츠공학", "스포츠과학과", None, "전공선택", 3.0, "2", "2", "unverified"),
    ("BX2001140", "생체고체역학", "의생명융합공학부", None, "전공선택", 3.0, "3", "1", "unverified"),
    ("BX2001130", "바이오 인공장기", "의생명융합공학부", None, "전공선택", 3.0, "4", "1", "unverified"),
    ("IE3500452", "통계적선형모형", "산업공학과", None, "전공선택", 3.0, "3", "1", "unverified"),
    ("LD2001630", "데이터분석론", "조경학과", None, "전공선택", 3.0, "2", "2", "unverified"),
]

SW_COMMON_CATEGORY = "일반선택"
SW_COMMON_CREDITS = 3.0
SW_COMMON_YEAR = "전학년"
SW_COMMON_SEMESTER = "전학기"

# 트랙별 인정 과목. (교과목번호, 교과목명, requirement_group) 3-튜플.
#
# 매칭은 course_code로만 한다 — 이름 매칭은 오매칭 위험이 크다(자료의
# '도서관데이터분석실습'은 실제로 LI2001639이고, 자료에 적힌 LI2001637은 현행
# '디지털자료관리'다). 다만 코드가 구버전인 경우도 있어(소셜미디어데이터분석은
# 자료 CO2001037이 DB에 없고 CO2001309가 현행), 그런 건 팀 확인 후 여기 코드를 고친다.
#
# requirement_group에 "(필수)"/"(택1-A)" 같은 하위 묶음을 담는다. flat
# graduation_requirements는 이수구분별 학점 합계만 담아 이런 조건을 표현할 수 없어서다.
# **판정 로직은 아직 없다** — 데이터만 보존하고, 14개 트랙을 다 받은 뒤 규칙 스키마를
# 설계한다.
TRACK_COURSES: dict[str, dict] = {
    "문헌정보데이터분석": {
        "rule": "학과전공과목 중 최소 4과목 이상 선택 + SW융합공통교과목 중 최소 2과목",
        "courses": [
            ("LI3400542", "정보시스템론", GROUP_DEPARTMENT_MAJOR),
            # 자료의 '문헌정보분석론'(LI3400427)은 2026 편제에 없고 이 과목으로 대체됨.
            ("LI2001635", "도서관데이터분석개론", GROUP_DEPARTMENT_MAJOR),
            ("LI3400547", "정보검색론", GROUP_DEPARTMENT_MAJOR),
            # 자료의 '도서관데이터분석실습' 자리. 코드는 그대로고 이름만 바뀌었다.
            ("LI2001637", "디지털자료관리", GROUP_DEPARTMENT_MAJOR),
            ("LI2001640", "메타데이터설계", GROUP_DEPARTMENT_MAJOR),
            ("LI2001645", "프로젝트관리론", GROUP_DEPARTMENT_MAJOR),
        ],
        # 공통교과목이 자료에 특정되지 않고 "중 최소 2과목"으로만 적혀 있어,
        # 개설된 공통교과목 전체를 후보로 붙인다.
        "sw_common_all": True,
    },
    "미디어데이터사이언스": {
        "rule": (
            "학과전공과목 15학점(7과목 중 5과목) + SW융합공통교과목 6학점. "
            "빅데이터분석의이해와활용 필수, 데이터저널리즘/소셜미디어데이터분석 중 1과목 필수. "
            "SW공통은 (데이터분석입문|AI이해를위한파이썬기초) 1과목 + "
            "(데이터리터러시의이해|AI리터러시의이해) 1과목."
        ),
        "courses": [
            ("CO3500882", "빅데이터분석의이해와활용", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            ("CO2200100", "커뮤니케이션연구방법론", GROUP_DEPARTMENT_MAJOR),
            ("CO2300715", "뉴미디어와사회", GROUP_DEPARTMENT_MAJOR),
            ("CO3000486", "온라인PR", GROUP_DEPARTMENT_MAJOR),
            ("CO3600447", "커뮤니케이션기초통계", GROUP_DEPARTMENT_MAJOR),
            ("CO2001071", "데이터저널리즘", f"{GROUP_DEPARTMENT_MAJOR}(택1-A)"),
            # 자료는 CO2001037이지만 DB에 없다. 이름·학과·학점·이수구분이 모두 일치하는
            # 현행 코드가 CO2001309 하나뿐이라 팀 확인 후 이쪽으로 연결.
            ("CO2001309", "소셜미디어데이터분석", f"{GROUP_DEPARTMENT_MAJOR}(택1-A)"),
            ("SF1101073", "데이터분석입문", f"{GROUP_SW_COMMON}(택1-A)"),
            ("SF1101074", "AI이해를위한파이썬기초", f"{GROUP_SW_COMMON}(택1-A)"),
            ("SF1101084", "데이터리터러시의이해", f"{GROUP_SW_COMMON}(택1-B)"),
            ("SF1101080", "AI리터러시의이해", f"{GROUP_SW_COMMON}(택1-B)"),
        ],
    },
    "데이터사이언스와복지": {
        # 5과목 15학점이 전부 지정 과목이라 "N과목 중 선택" 조건이 없다.
        # 교과목번호의 SW 접두는 소프트웨어가 아니라 사회복지학과 코드다.
        "rule": "학과전공과목 15학점(지정 5과목 전부) + SW융합공통교과목 중 2과목(6학점)",
        "courses": [
            ("SW2400655", "사회복지조사론", GROUP_DEPARTMENT_MAJOR),
            ("SW2000092", "사회복지자료분석론", GROUP_DEPARTMENT_MAJOR),
            ("SW2000088", "지역사회복지론", GROUP_DEPARTMENT_MAJOR),
            ("SW2000090", "사회복지행정론", GROUP_DEPARTMENT_MAJOR),
            ("SW2000087", "사회복지정책론", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "소셜데이터사이언스": {
        "rule": "학과전공과목 15학점(6과목 중 5과목 선택) + SW융합공통교과목 중 2과목(6학점)",
        "courses": [
            ("SO2100703", "사회조사방법론", GROUP_DEPARTMENT_MAJOR),
            ("SO1500550", "사회통계학", GROUP_DEPARTMENT_MAJOR),
            # 자료는 띄어쓰기, DB(AIS)는 붙여쓰기 — 공백 차이는 _squash가 흡수한다.
            ("SO2001652", "디지털과 영상사회학", GROUP_DEPARTMENT_MAJOR),
            ("SO3600456", "과학기술과 사회", GROUP_DEPARTMENT_MAJOR),
            ("SO2001653", "소셜데이터의 이해와분석", GROUP_DEPARTMENT_MAJOR),
            ("SO2800973", "인터넷과 정보사회", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "심리데이터사이언스": {
        "rule": "학과전공과목 15학점(8과목 중 5과목 선택) + SW융합공통교과목 중 2과목(6학점)",
        "courses": [
            ("PY3600441", "심리통계및실습(I)", GROUP_DEPARTMENT_MAJOR),
            ("PY3500222", "연구설계및실습", GROUP_DEPARTMENT_MAJOR),
            ("PY1600548", "과학으로서의심리학", GROUP_DEPARTMENT_MAJOR),
            ("PY3800687", "사회신경과학", GROUP_DEPARTMENT_MAJOR),
            ("PY2100847", "공학심리학", GROUP_DEPARTMENT_MAJOR),
            ("PY3500220", "감정과학", GROUP_DEPARTMENT_MAJOR),
            ("PY3600439", "임상신경심리학", GROUP_DEPARTMENT_MAJOR),
            ("PY3500217", "뇌정보처리", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "정치데이터사이언스": {
        "rule": "학과전공과목 12학점(지정 4과목 전부) + SW융합공통교과목 중 3과목(9학점)",
        "courses": [
            ("PD3100387", "정치학연구방법론", GROUP_DEPARTMENT_MAJOR),
            ("PD3100385", "외교정책론", GROUP_DEPARTMENT_MAJOR),
            ("PD2001650", "시민정치론", GROUP_DEPARTMENT_MAJOR),
            ("PD2001649", "정치철학의 쟁점", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    # TRACKS의 이름이 "행정관리과학(DMS)"라 base_name(첫 '(' 앞)은 "행정관리과학"이 된다.
    "행정관리과학": {
        "rule": (
            "학과전공과목 15학점(전필 2과목 필수 + 전선 중 3과목 선택) + "
            "SW융합공통교과목 중 2과목(6학점). 권장 공통과목: 데이터리터러시의이해, "
            "AI리터러시의이해, 데이터마이닝"
        ),
        "courses": [
            # 자료의 'R 기반 조사방법론'(PA2001673)은 DB에 없다. 행정학과 37과목 중
            # 조사방법론은 이것 하나뿐이고 이수구분·학년·학기(전공필수 2-1)가 정확히
            # 일치해 팀 확인 후 연결했다.
            ("PA2003845", "생성형 AI를 활용한 조사방법론", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            ("PA3600451", "공공데이터분석론", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            ("PA2001666", "GIS 기반 행정자료분석", GROUP_DEPARTMENT_MAJOR),
            ("PA2001669", "인공지능과 디지털 거버넌스", GROUP_DEPARTMENT_MAJOR),
            ("PA2001668", "빅데이터기반 정책결정론", GROUP_DEPARTMENT_MAJOR),
            ("PA2001667", "빅데이터기반 정책평가론", GROUP_DEPARTMENT_MAJOR),
            ("PA2001670", "지산학 연계 캡스톤 디자인(지역문제 액션러닝)", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "공공데이터분석": {
        "rule": "학과전공과목 15학점(지정 5과목 전부) + SW융합공통교과목 중 2과목(6학점)",
        "courses": [
            ("PP1600782", "공공관리의이해", GROUP_DEPARTMENT_MAJOR),
            ("PP3600195", "공공정책론", GROUP_DEPARTMENT_MAJOR),
            ("PP3300286", "e-정부론", GROUP_DEPARTMENT_MAJOR),
            ("PP3600120", "데이터정책론", GROUP_DEPARTMENT_MAJOR),
            ("PP3300288", "사회조사방법론", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "디지털패션": {
        "rule": (
            "학과전공과목 12학점(패션리테일링 필수 + 전선 중 3과목 선택) + "
            "SW융합공통교과목 중 3과목(9학점)"
        ),
        "courses": [
            ("CT3500922", "패션리테일링", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            # 자료 CT3600617 -> 현행 CT1501204. 의류학과 내 동명 과목이 이것 하나뿐이다.
            ("CT1501204", "디지털패션디자인", GROUP_DEPARTMENT_MAJOR),
            ("CT2600563", "텍스타일디자인CAD", GROUP_DEPARTMENT_MAJOR),
            ("CT3500208", "패션마켓리서치", GROUP_DEPARTMENT_MAJOR),
            ("CT2001288", "온라인패션비즈니스경영", GROUP_DEPARTMENT_MAJOR),
            # 자료 CT3500492 '어패럴패턴CAD' -> 현행 CT2003062로 이름이 확장됐다.
            # 학년·학기(4-1)가 같고 자료의 교과목 개요에도 3D 가상착의가 명시돼 있다.
            ("CT2003062", "어패럴패턴CAD및3D가상피팅", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "AI 스포츠과학": {
        "rule": (
            "학과전공과목 15학점 + SW융합공통교과목 중 2과목(6학점). "
            "공통과목은 데이터분석입문·메타버스활용프로젝트·데이터마이닝 3개로 한정된다."
        ),
        "courses": [
            # 아래 2건은 MISSING_COURSE_DEFS로 생성한 과목(개설 여부 미확인).
            ("SC3600515", "스폰서십마케팅", GROUP_DEPARTMENT_MAJOR),
            ("SC3300968", "스포츠공학", GROUP_DEPARTMENT_MAJOR),
            ("SC2600329", "운동처방", GROUP_DEPARTMENT_MAJOR),
            # 자료는 '...논문작성법', DB는 '...논문작성방법'. 코드가 같아 같은 과목이다.
            ("SC3600184", "스포츠통계처리및논문작성방법", GROUP_DEPARTMENT_MAJOR),
            ("SC2700167", "스포츠심리학", GROUP_DEPARTMENT_MAJOR),
            # 이 트랙만 공통과목을 3개로 특정한다(다른 트랙처럼 전체 후보가 아님).
            ("SF1101073", "데이터분석입문", f"{GROUP_SW_COMMON}(택2)"),
            ("SF1101081", "메타버스활용프로젝트", f"{GROUP_SW_COMMON}(택2)"),
            ("SF1101083", "데이터마이닝", f"{GROUP_SW_COMMON}(택2)"),
        ],
        # 참고: 스폰서십마케팅은 학과에 이름이 비슷한 SC2001898
        # (스폰서십효과측정과데이터분석실전가이드)이 있지만 이수구분·학기가 모두 달라
        # 같은 과목으로 보지 않고, 자료 코드 그대로 새로 만들었다.
    },
    "디자인컴퓨팅": {
        "rule": "학과전공과목 15학점(지정 5과목) + SW융합공통교과목 중 2과목(6학점)",
        # **전공 5과목 전부 DB에 없어 보류 상태다.** 개설 주체가 디자인학과가 아니라
        # 디자인앤테크놀로지전공인데 AIS 시드에 그 전공 과목이 들어오지 않은 것으로 보인다
        # (디자인학과에는 '컴퓨터그래픽(I)(II)'·'타이포그라피(I)(II)'만 있고 자료의
        # 컴퓨터그래픽스/피지컬컴퓨팅/키네틱타이포그래피/HCI/컴퓨터비전은 없다).
        # 5과목 전부 AIS 시드에 없어 MISSING_COURSE_DEFS로 직접 생성한다(시드 누락).
        "courses": [
            ("VF3500076", "컴퓨터그래픽스", GROUP_DEPARTMENT_MAJOR),
            ("VF3500077", "피지컬컴퓨팅", GROUP_DEPARTMENT_MAJOR),
            ("VF3500072", "키네틱타이포그래피", GROUP_DEPARTMENT_MAJOR),
            ("VF3600180", "HCI", GROUP_DEPARTMENT_MAJOR),
            ("VF3500081", "컴퓨터비전", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "바이오메디컬디바이스&데이터": {
        "rule": (
            "학과전공과목 15학점(회로이론·유기화학·생체고체역학 필수 + 나머지 5과목 중 2과목) + "
            "SW융합공통교과목 중 2과목(6학점, 데이터분석입문·데이터리터러시의이해·데이터마이닝)"
        ),
        "courses": [
            ("BX3600080", "회로이론", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            ("BX3600075", "유기화학", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            # 아래 2건은 MISSING_COURSE_DEFS로 생성한 과목(개설 여부 미확인).
            ("BX2001140", "생체고체역학", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            ("BX2001130", "바이오 인공장기", GROUP_DEPARTMENT_MAJOR),
            ("BX3600092", "바이오센서공학", GROUP_DEPARTMENT_MAJOR),
            ("BX3600428", "웨어러블 디바이스", GROUP_DEPARTMENT_MAJOR),
            ("BX2001183", "바이오이미징", GROUP_DEPARTMENT_MAJOR),
            ("BX3600099", "나노의학", GROUP_DEPARTMENT_MAJOR),
            ("SF1101073", "데이터분석입문", f"{GROUP_SW_COMMON}(택2)"),
            ("SF1101084", "데이터리터러시의이해", f"{GROUP_SW_COMMON}(택2)"),
            ("SF1101083", "데이터마이닝", f"{GROUP_SW_COMMON}(택2)"),
        ],
    },
    "산업AI": {
        "rule": (
            "학과전공과목 15학점(공학통계(I)·데이터마이닝 필수 + 8과목 중 3과목) + "
            "SW융합공통교과목 6학점: (AI이해를위한파이썬기초|창의적프로그래밍) 1과목 이상 + "
            "(인공지능기초수학|데이터분석입문) 1과목 이상"
        ),
        "courses": [
            ("IE2400210", "공학통계(I)", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            ("IE2400223", "데이터마이닝", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            ("IE3600657", "최적화개론", GROUP_DEPARTMENT_MAJOR),
            ("IE3500627", "산업데이터과학", GROUP_DEPARTMENT_MAJOR),
            ("IE3500452", "통계적선형모형", GROUP_DEPARTMENT_MAJOR),
            ("IE3600168", "인공지능개론", GROUP_DEPARTMENT_MAJOR),
            ("IE3500735", "스마트제조", GROUP_DEPARTMENT_MAJOR),
            # 자료 IE3600666 -> 현행 IE3600432 (산업공학과 내 동명 과목 유일)
            ("IE3600432", "시설계획및물류시스템", GROUP_DEPARTMENT_MAJOR),
            ("IE2001445", "딥러닝", GROUP_DEPARTMENT_MAJOR),
            ("IE3600669", "강화학습개론", GROUP_DEPARTMENT_MAJOR),
            ("SF1101074", "AI이해를위한파이썬기초", f"{GROUP_SW_COMMON}(택1-A)"),
            ("SF1101082", "창의적프로그래밍", f"{GROUP_SW_COMMON}(택1-A)"),
            ("SF1101085", "인공지능기초수학", f"{GROUP_SW_COMMON}(택1-B)"),
            ("SF1101073", "데이터분석입문", f"{GROUP_SW_COMMON}(택1-B)"),
        ],
    },
    "도시·환경·생태 데이터분석": {
        "rule": "학과전공과목 15학점(지정 5과목) + SW융합공통교과목 중 2과목(6학점). 2025 신설",
        "courses": [
            ("LD3600040", "조경공간정보분석", GROUP_DEPARTMENT_MAJOR),
            ("LD2001629", "데이터분석의 기초", GROUP_DEPARTMENT_MAJOR),
            ("LD2001630", "데이터분석론", GROUP_DEPARTMENT_MAJOR),
            ("LD2001631", "도시환경분석과시각화", GROUP_DEPARTMENT_MAJOR),
            # 자료 LD2001632 -> 현행 LD2003333 (조경학과 내 동명 과목 유일)
            ("LD2003333", "데이터기반 조경계획", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
}

# 개설 주체가 세부전공이라 상위 학과 밑에 붙인 것들 (기록용).
HOST_MAJOR_NOTE = {
    "디자인컴퓨팅": "디자인학과 디자인앤테크놀로지전공",
    "임베디드SW": "전기전자공학부 전자공학전공",
    "에너지IoT": "전기전자공학부 전기공학전공",
}

# (프로그램명, 단과대학, 개설학과)
TRACKS = [
    ("문헌정보데이터분석", "사회과학대학", "문헌정보학과"),
    ("미디어데이터사이언스", "사회과학대학", "미디어커뮤니케이션학과"),
    ("데이터사이언스와복지", "사회과학대학", "사회복지학과"),
    ("소셜데이터사이언스", "사회과학대학", "사회학과"),
    ("심리데이터사이언스", "사회과학대학", "심리학과"),
    ("정치데이터사이언스", "사회과학대학", "정치외교학과"),
    ("행정관리과학(DMS)", "사회과학대학", "행정학과"),
    ("공공데이터분석", "경제통상대학", "공공정책학부"),
    ("디지털패션", "생활과학대학", "의류학과"),
    ("AI 스포츠과학", "생활과학대학", "스포츠과학과"),
    ("디자인컴퓨팅", "예술대학", "디자인학과"),
    ("바이오메디컬디바이스&데이터", "정보의생명공학대학", "의생명융합공학부"),
    ("산업AI", "공과대학", "산업공학과"),
    ("도시·환경·생태 데이터분석", "생명자원과학대학", "조경학과"),
]

# 자료의 개설학과 약어 -> 라이브 계층의 학과명.
# 자료 각 연계전공 표의 "※개설학과" 범례에서 옮겼다. EE(전자공학전공)와
# ET(전기공학전공)는 둘 다 전기전자공학부 소속이라 학부 단위로 좁힌다
# (세부전공까지 좁히면 학부 공통 과목이 빠진다).
LINKED_HOST_DEPARTMENTS = {
    "CP": "정보컴퓨터공학부",
    "CB": "정보컴퓨터공학부",
    "MA": "수학과",
    "IE": "산업공학과",
    "EC": "경제학부",
    "DB": "경영학과",
    "ST": "통계학과",
    "DM": "기계공학부",
    "EE": "전기전자공학부",
    "ET": "전기전자공학부",
    "SF": SW_COMMON_DEPARTMENT,
}

# 연계전공 인정 과목. (개설학과 약어, 교과목명, 이수구분).
# 교과목번호가 프로그램 전용이라 쓸 수 없어 (개설학과, 이름)으로 찾는다
# — _resolve_linked_courses 참고.
GROUP_LINKED_REQUIRED = "전공필수"
GROUP_LINKED_ELECTIVE = "전공선택"

LINKED_COURSES: dict[str, dict] = {
    "산업수학SW": {
        "rule": "전공필수 29학점 + 전공선택 19학점, 총 48학점",
        "courses": [
            ("CP", "프로그래밍원리와실습", GROUP_LINKED_REQUIRED),
            ("CP", "C++프로그래밍과실습", GROUP_LINKED_REQUIRED),
            ("MA", "정수론", GROUP_LINKED_REQUIRED),
            ("MA", "미분방정식(II)", GROUP_LINKED_REQUIRED),
            ("CP", "자료구조", GROUP_LINKED_REQUIRED),
            ("MA", "확률과통계", GROUP_LINKED_REQUIRED),
            ("MA", "수학적프로그래밍", GROUP_LINKED_REQUIRED),
            ("MA", "수리모델론", GROUP_LINKED_REQUIRED),
            ("MA", "산업수학및실무", GROUP_LINKED_REQUIRED),
            ("CP", "컴퓨터및프로그래밍입문", GROUP_LINKED_ELECTIVE),
            ("MA", "수학(II)", GROUP_LINKED_ELECTIVE),
            ("EC", "미시경제학", GROUP_LINKED_ELECTIVE),
            ("MA", "선형대수학(I)", GROUP_LINKED_ELECTIVE),
            # 자료는 이산수학(I)(1-1)/이산수학(II)(2-2)로 나뉘지만 DB는 둘 다 '이산수학'이다.
            # 학년·학기가 CB1501027(전공기초 1-1)·CB2001104(전공선택 2-2)와 정확히 맞아
            # 같은 과목으로 보고 이름 '이산수학'으로 연결한다(동명 후보를 모두 붙이는
            # 연계전공 원칙에 따라 두 과목이 함께 잡힌다).
            ("CP", "이산수학", GROUP_LINKED_ELECTIVE),
            ("EE", "전자기학(I)", GROUP_LINKED_ELECTIVE),
            ("MA", "해석학(I)", GROUP_LINKED_ELECTIVE),
            ("DM", "유체역학", GROUP_LINKED_ELECTIVE),
            ("DB", "재무관리", GROUP_LINKED_ELECTIVE),
            ("ST", "통계프로그래밍언어(I)", GROUP_LINKED_ELECTIVE),
            ("CP", "플랫폼기반프로그래밍", GROUP_LINKED_ELECTIVE),
            ("MA", "보험수학입문", GROUP_LINKED_ELECTIVE),
            ("MA", "실변수함수론(I)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(I)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(II)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(III)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(IV)", GROUP_LINKED_ELECTIVE),
        ],
    },
    "빅데이터": {
        "rule": "전공필수 32학점 + 전공선택 16학점, 총 48학점",
        "courses": [
            ("CP", "프로그래밍원리와실습", GROUP_LINKED_REQUIRED),
            ("CP", "C++프로그래밍과실습", GROUP_LINKED_REQUIRED),
            ("IE", "공학통계(I)", GROUP_LINKED_REQUIRED),
            ("IE", "경영과학(I)", GROUP_LINKED_REQUIRED),
            ("IE", "공학통계(II)", GROUP_LINKED_REQUIRED),
            ("CP", "자료구조", GROUP_LINKED_REQUIRED),
            ("CP", "소프트웨어공학", GROUP_LINKED_REQUIRED),
            ("CP", "데이터베이스", GROUP_LINKED_REQUIRED),
            ("IE", "데이터베이스", GROUP_LINKED_REQUIRED),
            ("CP", "데이터마이닝", GROUP_LINKED_ELECTIVE),
            ("IE", "데이터마이닝", GROUP_LINKED_ELECTIVE),
            ("CP", "인공지능개론", GROUP_LINKED_ELECTIVE),
            ("IE", "인공지능개론", GROUP_LINKED_ELECTIVE),
            ("CP", "컴퓨터및프로그래밍입문", GROUP_LINKED_ELECTIVE),
            ("IE", "경제성공학", GROUP_LINKED_ELECTIVE),
            ("IE", "산업데이터과학", GROUP_LINKED_ELECTIVE),
            ("IE", "기술경영", GROUP_LINKED_ELECTIVE),
            ("CP", "웹응용프로그래밍", GROUP_LINKED_ELECTIVE),
            ("CP", "플랫폼기반프로그래밍", GROUP_LINKED_ELECTIVE),
            ("IE", "경영과학(II)", GROUP_LINKED_ELECTIVE),
            ("CP", "운영체제", GROUP_LINKED_ELECTIVE),
            ("CP", "컴퓨터구조", GROUP_LINKED_ELECTIVE),
            ("IE", "경영정보시스템", GROUP_LINKED_ELECTIVE),
            ("IE", "생산시스템공학", GROUP_LINKED_ELECTIVE),
            ("IE", "스마트서비스설계", GROUP_LINKED_ELECTIVE),
            ("CP", "사물인터넷", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(I)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(II)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(III)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(IV)", GROUP_LINKED_ELECTIVE),
        ],
    },
    "임베디드SW": {
        "rule": "전공필수 31학점 + 전공선택 17학점, 총 48학점",
        "courses": [
            ("CP", "프로그래밍원리와실습", GROUP_LINKED_REQUIRED),
            ("EE", "AI프로그래밍", GROUP_LINKED_REQUIRED),
            ("EE", "회로이론(I)", GROUP_LINKED_REQUIRED),
            ("CP", "C++프로그래밍과실습", GROUP_LINKED_REQUIRED),
            ("EE", "전자기학(I)", GROUP_LINKED_REQUIRED),
            ("EE", "신호및시스템", GROUP_LINKED_REQUIRED),
            ("EE", "전자회로(I)", GROUP_LINKED_REQUIRED),
            ("CP", "자료구조", GROUP_LINKED_REQUIRED),
            ("CP", "운영체제", GROUP_LINKED_REQUIRED),
            ("CP", "컴퓨터구조", GROUP_LINKED_REQUIRED),
            ("EE", "컴퓨터구조", GROUP_LINKED_REQUIRED),
            ("CP", "임베디드시스템", GROUP_LINKED_REQUIRED),
            ("EE", "임베디드시스템", GROUP_LINKED_REQUIRED),
            ("CP", "컴퓨터및프로그래밍입문", GROUP_LINKED_ELECTIVE),
            ("CP", "유닉스기초", GROUP_LINKED_ELECTIVE),
            ("CP", "플랫폼기반프로그래밍", GROUP_LINKED_ELECTIVE),
            ("CP", "시스템소프트웨어", GROUP_LINKED_ELECTIVE),
            ("EE", "마이크로프로세서응용", GROUP_LINKED_ELECTIVE),
            ("EE", "수치해석", GROUP_LINKED_ELECTIVE),
            ("EE", "제어공학", GROUP_LINKED_ELECTIVE),
            ("CP", "유닉스응용프로그래밍", GROUP_LINKED_ELECTIVE),
            ("CP", "데이터통신", GROUP_LINKED_ELECTIVE),
            ("EE", "데이터통신", GROUP_LINKED_ELECTIVE),
            ("EE", "디지털시스템설계", GROUP_LINKED_ELECTIVE),
            ("EE", "제어시스템설계", GROUP_LINKED_ELECTIVE),
            ("CP", "컴퓨터네트워크", GROUP_LINKED_ELECTIVE),
            ("CP", "컴퓨터비전개론", GROUP_LINKED_ELECTIVE),
            ("EE", "SoC설계개론", GROUP_LINKED_ELECTIVE),
            ("EE", "디지털신호처리", GROUP_LINKED_ELECTIVE),
            ("EE", "디지털통신개론", GROUP_LINKED_ELECTIVE),
            ("CP", "임베디드소프트웨어설계", GROUP_LINKED_ELECTIVE),
            ("EE", "스마트제어시스템", GROUP_LINKED_ELECTIVE),
            ("CP", "사물인터넷", GROUP_LINKED_ELECTIVE),
            ("CP", "인공지능개론", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(I)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(II)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(III)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(IV)", GROUP_LINKED_ELECTIVE),
        ],
    },
    "에너지IoT": {
        "rule": "전공필수 28학점 + 전공선택 20학점, 총 48학점",
        "courses": [
            ("CP", "전기전자공학개론", GROUP_LINKED_REQUIRED),
            ("ET", "전기회로(I)", GROUP_LINKED_REQUIRED),
            ("CP", "프로그래밍원리와실습", GROUP_LINKED_REQUIRED),
            ("ET", "AI프로그래밍", GROUP_LINKED_REQUIRED),
            ("CP", "C++프로그래밍과실습", GROUP_LINKED_REQUIRED),
            ("ET", "전자기학(I)", GROUP_LINKED_REQUIRED),
            ("ET", "전기회로(II)", GROUP_LINKED_REQUIRED),
            ("CP", "자료구조", GROUP_LINKED_REQUIRED),
            ("ET", "자료구조", GROUP_LINKED_REQUIRED),
            ("ET", "전자회로(I)", GROUP_LINKED_REQUIRED),
            ("ET", "컴퓨터구조", GROUP_LINKED_REQUIRED),
            ("CP", "컴퓨터구조", GROUP_LINKED_REQUIRED),
            ("CP", "소프트웨어공학", GROUP_LINKED_REQUIRED),
            ("CP", "컴퓨터및프로그래밍입문", GROUP_LINKED_ELECTIVE),
            ("ET", "프로그래밍언어", GROUP_LINKED_ELECTIVE),
            ("ET", "논리회로및설계", GROUP_LINKED_ELECTIVE),
            ("CP", "논리회로및설계", GROUP_LINKED_ELECTIVE),
            ("CP", "유닉스기초", GROUP_LINKED_ELECTIVE),
            ("ET", "신호및시스템", GROUP_LINKED_ELECTIVE),
            ("ET", "파이썬데이터사이언스", GROUP_LINKED_ELECTIVE),
            ("CP", "플랫폼기반프로그래밍", GROUP_LINKED_ELECTIVE),
            ("ET", "확률통계", GROUP_LINKED_ELECTIVE),
            ("CP", "확률통계", GROUP_LINKED_ELECTIVE),
            ("CP", "컴퓨터알고리즘", GROUP_LINKED_ELECTIVE),
            ("CP", "데이터통신", GROUP_LINKED_ELECTIVE),
            ("ET", "전기기기(I)", GROUP_LINKED_ELECTIVE),
            ("ET", "제어공학(I)", GROUP_LINKED_ELECTIVE),
            ("CP", "운영체제", GROUP_LINKED_ELECTIVE),
            ("ET", "마이크로프로세서응용", GROUP_LINKED_ELECTIVE),
            ("CP", "데이터베이스", GROUP_LINKED_ELECTIVE),
            ("CP", "임베디드시스템", GROUP_LINKED_ELECTIVE),
            ("ET", "전력전자", GROUP_LINKED_ELECTIVE),
            ("CP", "컴퓨터네트워크", GROUP_LINKED_ELECTIVE),
            ("ET", "수치해석", GROUP_LINKED_ELECTIVE),
            ("ET", "전력공학(I)", GROUP_LINKED_ELECTIVE),
            ("CP", "정보보안", GROUP_LINKED_ELECTIVE),
            ("ET", "플라즈마공학", GROUP_LINKED_ELECTIVE),
            ("ET", "전동기제어공학", GROUP_LINKED_ELECTIVE),
            ("CP", "사물인터넷", GROUP_LINKED_ELECTIVE),
            ("ET", "전력경제및스마트그리드", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(I)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(II)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(III)", GROUP_LINKED_ELECTIVE),
            ("SF", "소프트웨어융합기초(IV)", GROUP_LINKED_ELECTIVE),
        ],
    },
    "산업AI": {
        "rule": (
            "전공필수 12학점 + 전공선택 36학점, 총 48학점. "
            "전공필수는 4과목(12학점)을 선택하되 반드시 3개 이상의 학과 개설 과목을 이수해야 함"
        ),
        "courses": [
            ("IE", "최적화개론", GROUP_LINKED_REQUIRED),
            ("CB", "인공지능수학", GROUP_LINKED_REQUIRED),
            ("EE", "머신러닝을위한기초수학", GROUP_LINKED_REQUIRED),
            ("ET", "AI프로그래밍", GROUP_LINKED_REQUIRED),
            ("EE", "AI프로그래밍", GROUP_LINKED_REQUIRED),
            ("CB", "AI프로그래밍", GROUP_LINKED_REQUIRED),
            ("IE", "산업데이터과학", GROUP_LINKED_REQUIRED),
            ("CB", "데이터과학입문", GROUP_LINKED_REQUIRED),
            ("ET", "파이썬데이터사이언스", GROUP_LINKED_REQUIRED),
            ("CB", "인공지능개론", GROUP_LINKED_REQUIRED),
            ("IE", "인공지능개론", GROUP_LINKED_REQUIRED),
            ("EE", "인공지능개론", GROUP_LINKED_REQUIRED),
            ("CB", "머신러닝", GROUP_LINKED_REQUIRED),
            ("ET", "머신러닝", GROUP_LINKED_REQUIRED),
            ("CB", "딥러닝프로그래밍", GROUP_LINKED_REQUIRED),
            ("IE", "딥러닝", GROUP_LINKED_REQUIRED),
            ("IE", "산업인공지능응용", GROUP_LINKED_ELECTIVE),
            ("IE", "공학통계(I)", GROUP_LINKED_ELECTIVE),
            ("ET", "논리회로및설계", GROUP_LINKED_ELECTIVE),
            ("CB", "웹응용프로그래밍", GROUP_LINKED_ELECTIVE),
            ("CB", "자료구조", GROUP_LINKED_ELECTIVE),
            ("ET", "자료구조", GROUP_LINKED_ELECTIVE),
            ("ET", "확률통계", GROUP_LINKED_ELECTIVE),
            ("CB", "컴퓨터알고리즘", GROUP_LINKED_ELECTIVE),
            ("IE", "통계적선형모형", GROUP_LINKED_ELECTIVE),
            ("EE", "수치해석", GROUP_LINKED_ELECTIVE),
            ("EE", "제어공학", GROUP_LINKED_ELECTIVE),
            ("ET", "제어공학(I)", GROUP_LINKED_ELECTIVE),
            ("EE", "마이크로프로세서응용", GROUP_LINKED_ELECTIVE),
            ("IE", "데이터마이닝", GROUP_LINKED_ELECTIVE),
            ("CB", "데이터마이닝", GROUP_LINKED_ELECTIVE),
            ("IE", "데이터베이스", GROUP_LINKED_ELECTIVE),
            ("CB", "데이터베이스", GROUP_LINKED_ELECTIVE),
            ("ET", "제어공학(II)", GROUP_LINKED_ELECTIVE),
            ("EE", "제어시스템설계", GROUP_LINKED_ELECTIVE),
            ("IE", "시뮬레이션", GROUP_LINKED_ELECTIVE),
            ("IE", "스마트제조", GROUP_LINKED_ELECTIVE),
            ("CB", "생성모델", GROUP_LINKED_ELECTIVE),
            ("ET", "전력경제및스마트그리드", GROUP_LINKED_ELECTIVE),
            ("EE", "임베디드시스템", GROUP_LINKED_ELECTIVE),
            ("CB", "컴퓨터비전개론", GROUP_LINKED_ELECTIVE),
            ("CB", "지능형IoT플랫폼", GROUP_LINKED_ELECTIVE),
            ("ET", "지능형로봇공학", GROUP_LINKED_ELECTIVE),
            ("EE", "AI바이오의료영상", GROUP_LINKED_ELECTIVE),
            ("IE", "강화학습개론", GROUP_LINKED_ELECTIVE),
            ("EE", "데이터통신", GROUP_LINKED_ELECTIVE),
            ("CB", "인간컴퓨터상호작용", GROUP_LINKED_ELECTIVE),
        ],
    },
}

# 연계전공은 총 48학점이 전공필수/전공선택으로 나뉘고 자료에 그 숫자가 명시돼 있다.
# flat graduation_requirements의 required_major_required / required_major_elective에
# 그대로 담는다. (융합트랙은 "학과전공 + SW공통"이라는 다른 축이라 총학점만 담는다.)
LINKED_CREDIT_SPLIT = {
    "산업수학SW": (29, 19),
    "빅데이터": (32, 16),
    "임베디드SW": (31, 17),
    "에너지IoT": (28, 20),
    "산업AI": (12, 36),
}

LINKED_MAJORS = [
    ("산업수학SW", "자연과학대학", "수학과"),
    ("빅데이터", "공과대학", "산업공학과"),
    ("임베디드SW", "공과대학", "전기전자공학부"),
    ("에너지IoT", "공과대학", "전기전자공학부"),
    ("산업AI", "공과대학", "산업공학과"),
]

# SW융합전공. 핀테크융합전공은 이미 `departments`에 독립 편제 단위로 존재하므로
# (경영대학 소속, 자체 과목 47개 + 주전공 졸업요건 보유) majors 행을 새로 만들지 않고,
# 그 학과에 다중전공용 요건 행만 추가한다. 같은 프로그램을 두 군데로 쪼개지 않기 위함.
CONVERGENCE_MAJORS_AS_DEPARTMENT = [
    ("핀테크융합전공", "경영대학", "핀테크융합전공"),
]


def _squash(name: str) -> str:
    """과목명 비교용 정규화. 공백 차이만 흡수한다."""
    return name.replace(" ", "").strip()


def _resolve_linked_courses(db, host_department: str, course_name: str) -> list[Course]:
    """연계전공 인정 과목을 (개설학과, 과목명)으로 찾는다. 후보가 여럿이면 모두 돌려준다.

    연계전공은 교과목번호가 프로그램 전용이라(같은 '프로그래밍원리와실습'이
    산업수학SW는 MS1600702, 빅데이터는 BD1600702) courses의 course_code로 매칭할 수
    없다. 뒷 7자리가 과목 고유번호처럼 보이지만 실제 개설학과는 다른 번호를 쓰는
    경우가 많아(자료의 CP 과목이 뒷자리로는 의생명융합공학부에 잡힘) 신뢰할 수 없다.

    그래서 자료의 개설학과 표기로 범위를 좁힌 뒤 이름으로 찾는다. 한 학부 안에서
    세부전공별로 같은 이름의 과목이 따로 개설된 경우(정보컴퓨터공학부의 컴퓨터공학·
    인공지능·디자인테크놀로지전공)는 후보를 모두 인정 과목으로 붙인다 — 연계전공은
    "2개 이상 학과가 각 전공에 개설된 교과목을 선택하여 편성"하는 제도라 학생이 어느
    전공에서 듣든 인정되는 것이 자연스럽고, 하나만 고르면 임의 선택이 되기 때문이다.
    """
    return list(
        db.scalars(
            select(Course)
            .join(Department, Department.id == Course.department_id)
            .where(
                Department.name == host_department,
                func.replace(Course.course_name, " ", "") == _squash(course_name),
            )
            .order_by(Course.course_code)
        ).all()
    )


def _find_department(db, school_id: int, college_name: str, department_name: str) -> Department | None:
    return db.scalars(
        select(Department)
        .join(College, College.id == Department.college_id)
        .where(
            College.school_id == school_id,
            College.name == college_name,
            Department.name == department_name,
        )
    ).first()


def _get_or_create_major(db, department_id: int, name: str) -> tuple[Major, bool]:
    major = db.scalars(
        select(Major).where(Major.department_id == department_id, Major.name == name)
    ).first()
    if major is not None:
        return major, False
    major = Major(department_id=department_id, name=name)
    db.add(major)
    db.flush()
    return major, True


def _ensure_sw_common_courses(db, school_id: int) -> tuple[list[Course], int, int]:
    """소프트웨어융합교육원 학과와 SW융합 공통교과목을 만들어 둔다(멱등).

    AIS 시드가 학과 편제만 가져와서 이 과목들이 courses에 아예 없다. 트랙 요건의
    6~9학점을 차지하므로 여기서 직접 만든다.
    """
    college = db.scalars(
        select(College).where(College.school_id == school_id, College.name == SW_COMMON_COLLEGE)
    ).first()
    if college is None:
        college = College(school_id=school_id, name=SW_COMMON_COLLEGE)
        db.add(college)
        db.flush()

    department = db.scalars(
        select(Department).where(
            Department.college_id == college.id, Department.name == SW_COMMON_DEPARTMENT
        )
    ).first()
    if department is None:
        department = Department(college_id=college.id, name=SW_COMMON_DEPARTMENT)
        db.add(department)
        db.flush()

    courses: list[Course] = []
    created = existing = 0
    definitions = [(c, n, SW_COMMON_SEMESTER) for c, n in SW_COMMON_COURSE_DEFS]
    # 소프트웨어융합기초는 계절학기 개설이라 학기값만 다르다. 연계전공 전공선택에만
    # 쓰이므로 SW융합공통교과목 후보(sw_common_all)에는 넣지 않는다.
    definitions += [(c, n, SW_FOUNDATION_SEMESTER) for c, n in SW_FOUNDATION_COURSE_DEFS]

    for code, name, semester in definitions:
        course = db.scalars(select(Course).where(Course.course_code == code)).first()
        if course is None:
            course = Course(
                course_code=code,
                course_name=name,
                department_id=department.id,
                category=SW_COMMON_CATEGORY,
                credits=SW_COMMON_CREDITS,
                year=SW_COMMON_YEAR,
                semester=semester,
            )
            db.add(course)
            db.flush()
            created += 1
        else:
            existing += 1
        if semester == SW_COMMON_SEMESTER:
            courses.append(course)
    return courses, created, existing


def _upsert_program_courses(
    db, department_id: int, major_id: int | None, spec: dict, sw_common: list[Course]
) -> tuple[int, int, list[str]]:
    """트랙의 인정 과목을 program_courses에 멱등 upsert한다.

    course_code로만 매칭하고, 못 찾았거나 이름이 다르면 조용히 넘기지 않고 돌려준다.
    """
    entries: list[tuple[str, str, str]] = list(spec["courses"])
    if spec.get("sw_common_all"):
        # 자료가 공통교과목을 특정하지 않고 "중 최소 N과목"으로만 적은 트랙.
        entries += [(c.course_code, c.course_name, GROUP_SW_COMMON) for c in sw_common]

    created = existing = 0
    missing: list[str] = []
    for code, expected_name, group in entries:
        course = db.scalars(select(Course).where(Course.course_code == code)).first()
        if course is None:
            missing.append(f"{code} ({expected_name}) — DB에 없음")
            continue
        # 공백만 다른 건 같은 과목으로 본다. 자료는 '과학기술과 사회'처럼 띄어 쓰고
        # DB(AIS)는 '과학기술과사회'로 붙여 쓰는 경우가 흔하다. 그 외 차이는
        # 코드 재부여/과목 개편일 수 있어 자동으로 넘기지 않고 사람이 확인한다.
        if _squash(course.course_name) != _squash(expected_name):
            missing.append(f"{code}: DB '{course.course_name}' != 자료 '{expected_name}'")
            continue
        row = db.scalars(
            select(ProgramCourse).where(
                ProgramCourse.department_id == department_id,
                ProgramCourse.major_id.is_(None)
                if major_id is None
                else ProgramCourse.major_id == major_id,
                ProgramCourse.course_id == course.id,
                ProgramCourse.curriculum_year == CURRICULUM_YEAR,
            )
        ).first()
        if row is not None:
            row.requirement_group = group
            row.category = course.category
            existing += 1
            continue
        db.add(
            ProgramCourse(
                department_id=department_id,
                major_id=major_id,
                course_id=course.id,
                requirement_group=group,
                category=course.category,
                curriculum_year=CURRICULUM_YEAR,
            )
        )
        created += 1
    return created, existing, missing


def _ensure_missing_courses(db, school_id: int) -> tuple[int, int, list[str]]:
    """AIS 시드에 없는 과목을 자료 기준으로 만든다(멱등). MISSING_COURSE_DEFS 주석 참고."""
    created = existing = 0
    notes: list[str] = []
    for code, name, dept_name, major_name, category, credits, year, semester, reason in (
        MISSING_COURSE_DEFS
    ):
        course = db.scalars(select(Course).where(Course.course_code == code)).first()
        if course is not None:
            existing += 1
            continue
        department = _find_department_any_college(db, school_id, dept_name)
        if department is None:
            notes.append(f"{code} {name} — 학과 '{dept_name}' 없음")
            continue
        major_id = None
        if major_name:
            major = db.scalars(
                select(Major).where(
                    Major.department_id == department.id, Major.name == major_name
                )
            ).first()
            if major is None:
                notes.append(f"{code} {name} — 전공 '{major_name}' 없음")
                continue
            major_id = major.id
        db.add(
            Course(
                course_code=code,
                course_name=name,
                department_id=department.id,
                major_id=major_id,
                category=category,
                credits=credits,
                year=year,
                semester=semester,
            )
        )
        created += 1
        if reason == "unverified":
            notes.append(f"{code} {name} — 개설 여부 미확인(학사 확인 필요)")
    db.flush()
    return created, existing, notes


def _find_department_any_college(db, school_id: int, name: str) -> Department | None:
    return db.scalars(
        select(Department)
        .join(College, College.id == Department.college_id)
        .where(College.school_id == school_id, Department.name == name)
    ).first()


def _upsert_linked_courses(
    db, department_id: int, major_id: int, spec: dict
) -> tuple[int, int, list[str]]:
    """연계전공 인정 과목을 program_courses에 멱등 upsert한다.

    (개설학과, 이름)으로 찾고 후보가 여럿이면 모두 붙인다 — _resolve_linked_courses 참고.
    """
    created = existing = 0
    missing: list[str] = []
    # 한 프로그램 안에서 같은 과목이 두 번 잡히는 걸 막는다. 자료가 개설학과를
    # EE(전자공학전공)/ET(전기공학전공)로 나눠 적어도 둘 다 전기전자공학부로 해석되므로
    # 따로 적힌 두 항목이 동일한 과목 집합으로 풀린다(예: 산업AI의 AI프로그래밍).
    # 먼저 나온 이수구분을 유지한다 — 전공필수가 전공선택보다 앞에 오도록 데이터를 적었다.
    seen_course_ids: set[int] = set()
    for abbrev, course_name, group in spec["courses"]:
        host = LINKED_HOST_DEPARTMENTS.get(abbrev)
        if host is None:
            missing.append(f"{abbrev} {course_name} — 개설학과 약어 미매핑")
            continue
        courses = _resolve_linked_courses(db, host, course_name)
        if not courses:
            missing.append(f"{host} '{course_name}' — 해당 학과에 없음")
            continue
        for course in courses:
            if course.id in seen_course_ids:
                continue
            seen_course_ids.add(course.id)
            row = db.scalars(
                select(ProgramCourse).where(
                    ProgramCourse.department_id == department_id,
                    # 같은 파일 832행과 같은 형태여야 한다 — `== None`은 `= NULL`이라
                    # 학과 단위 행(major_id IS NULL)이 조회에 안 걸려 중복이 쌓인다.
                    ProgramCourse.major_id.is_(None)
                    if major_id is None
                    else ProgramCourse.major_id == major_id,
                    ProgramCourse.course_id == course.id,
                    ProgramCourse.curriculum_year == CURRICULUM_YEAR,
                )
            ).first()
            if row is not None:
                row.requirement_group = group
                row.category = course.category
                existing += 1
                continue
            db.add(
                ProgramCourse(
                    department_id=department_id,
                    major_id=major_id,
                    course_id=course.id,
                    requirement_group=group,
                    category=course.category,
                    curriculum_year=CURRICULUM_YEAR,
                )
            )
            created += 1
    return created, existing, missing


def _upsert_requirement(
    db,
    department_id: int,
    major_id: int | None,
    total_credits: int | None,
    major_required: int | None = None,
    major_elective: int | None = None,
) -> str:
    """같은 (department, major, program_type, curriculum_year) 행을 덮어쓴다(멱등).

    major_required/major_elective는 연계전공처럼 자료에 이수구분별 학점이 명시된
    경우에만 채운다. 융합트랙은 "학과전공과목 + SW융합공통교과목"이라는 다른 축으로
    쪼개져 있어 flat 테이블의 이수구분 컬럼에 담을 수 없으므로 None으로 둔다.
    """
    existing = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.department_id == department_id,
            GraduationRequirement.major_id.is_(None)
            if major_id is None
            else GraduationRequirement.major_id == major_id,
            GraduationRequirement.program_type == PROGRAM_TYPE,
            GraduationRequirement.curriculum_year == CURRICULUM_YEAR,
        )
    ).first()
    if existing is not None:
        existing.required_total_credits = total_credits
        existing.required_major_required = major_required
        existing.required_major_elective = major_elective
        return "updated"
    db.add(
        GraduationRequirement(
            department_id=department_id,
            major_id=major_id,
            program_type=PROGRAM_TYPE,
            curriculum_year=CURRICULUM_YEAR,
            required_major_required=major_required,
            required_major_elective=major_elective,
            required_total_credits=total_credits,
        )
    )
    return "created"


def seed(apply: bool) -> int:
    db = SessionLocal()
    created_majors = updated_reqs = created_reqs = 0
    created_courses = existing_courses = 0
    skipped: list[str] = []
    try:
        school = db.scalars(select(School).where(School.name == "부산대학교")).first()
        if school is None:
            print("!! 학교 '부산대학교'가 없습니다. seed_school_hierarchy를 먼저 실행하세요.")
            return 1

        sw_common_courses, sw_new, sw_old = _ensure_sw_common_courses(db, school.id)
        print(
            f"  [공통] {SW_COMMON_DEPARTMENT} 개설 SW융합공통교과목 "
            f"신규 {sw_new} / 기존 {sw_old}"
        )
        miss_new, miss_old, miss_notes = _ensure_missing_courses(db, school.id)
        print(f"  [보완] AIS 시드 누락 과목 신규 {miss_new} / 기존 {miss_old}")
        for note in miss_notes:
            print(f"         ! {note}")
        print()

        plan: list[tuple[str, str, str, str, int | None]] = []
        for name, college, dept in TRACKS:
            if name in _EXCLUDED_TRACKS:
                skipped.append(f"{name} (제외 목록)")
                continue
            plan.append((f"{name}{TRACK_SUFFIX}", college, dept, "트랙", TRACK_TOTAL_CREDITS))
        for name, college, dept in LINKED_MAJORS:
            plan.append((f"{name}{LINKED_SUFFIX}", college, dept, "연계", LINKED_TOTAL_CREDITS))

        for major_name, college_name, department_name, kind, credits in plan:
            department = _find_department(db, school.id, college_name, department_name)
            if department is None:
                skipped.append(f"{major_name} — 개설학과 미매칭({college_name}>{department_name})")
                continue
            major, is_new = _get_or_create_major(db, department.id, major_name)
            created_majors += int(is_new)
            # base_name은 아래 요건/과목 조회에 모두 쓰이므로 반드시 먼저 계산한다.
            # (예전에 사용 뒤에 계산해서 각 프로그램이 직전 반복의 이름으로 학점을
            #  찾는 off-by-one 버그가 있었다.)
            base_name = major_name.split("(")[0]
            split = LINKED_CREDIT_SPLIT.get(base_name) if kind == "연계" else None
            action = _upsert_requirement(
                db, department.id, major.id, credits,
                major_required=split[0] if split else None,
                major_elective=split[1] if split else None,
            )
            created_reqs += int(action == "created")
            updated_reqs += int(action == "updated")
            note = HOST_MAJOR_NOTE.get(base_name)
            suffix = f"  (실제 개설: {note})" if note else ""
            print(
                f"  [{kind}] {department_name:22} > {major_name:34} "
                f"{credits}학점 major={'NEW' if is_new else 'exist'} req={action}{suffix}"
            )

            # TRACK_COURSES는 융합트랙 전용이다. kind로 거르지 않으면 같은 이름의
            # 연계전공이 트랙 과목을 가져간다 — 산업공학과에는 '산업AI'가 트랙(21학점)과
            # 연계전공(48학점)으로 둘 다 있어서 base_name만으로는 구분되지 않는다.
            spec = TRACK_COURSES.get(base_name) if kind == "트랙" else None
            linked_spec = LINKED_COURSES.get(base_name) if kind == "연계" else None
            if linked_spec is not None:
                l_new, l_old, l_missing = _upsert_linked_courses(
                    db, department.id, major.id, linked_spec
                )
                created_courses += l_new
                existing_courses += l_old
                print(f"         └ 인정과목 신규 {l_new} / 기존 {l_old}  (이수 규칙 판정 미구현)")
                for item in l_missing:
                    skipped.append(f"{major_name} 과목 {item}")
            if spec is not None:
                c_new, c_old, c_missing = _upsert_program_courses(
                    db, department.id, major.id, spec, sw_common_courses
                )
                created_courses += c_new
                existing_courses += c_old
                print(f"         └ 인정과목 신규 {c_new} / 기존 {c_old}  (이수 규칙 판정 미구현)")
                for item in c_missing:
                    skipped.append(f"{major_name} 과목 {item}")

        # SW융합전공: 이미 독립 학과로 존재하는 프로그램은 요건 행만 추가한다.
        for label, college_name, department_name in CONVERGENCE_MAJORS_AS_DEPARTMENT:
            department = _find_department(db, school.id, college_name, department_name)
            if department is None:
                skipped.append(f"{label} — 학과 미매칭({college_name}>{department_name})")
                continue
            action = _upsert_requirement(db, department.id, None, None)
            created_reqs += int(action == "created")
            updated_reqs += int(action == "updated")
            print(
                f"  [융합] {department_name:22} > (학과 자체{CONVERGENCE_SUFFIX})".ljust(66)
                + f" 최소전공학점 미상 req={action}"
            )

        print()
        print(
            f"majors 신규 {created_majors} / 요건 신규 {created_reqs} 갱신 {updated_reqs}"
            f" / 인정과목 신규 {created_courses} 기존 {existing_courses}"
        )
        if skipped:
            print("건너뜀:")
            for item in skipped:
                print(f"  - {item}")

        if apply:
            db.commit()
            print(">>> 커밋 완료")
        else:
            db.rollback()
            print(">>> dry-run (롤백). 실제 반영하려면 --apply")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="실제 DB에 반영(기본은 dry-run)")
    args = parser.parse_args()
    return seed(apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())

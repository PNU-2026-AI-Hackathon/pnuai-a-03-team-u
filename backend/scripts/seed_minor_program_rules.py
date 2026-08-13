"""부전공 이수기준 시드 스크립트

`raw_data/manual_staging/01_graduation_requirements/by_department/` 아래 md 파일로
정리된 학과별 부전공 요건을 `graduation_requirements.special_rules` (JSONB) +
`program_courses`에 반영한다.

CLAUDE.md 원칙에 따라:
  1. 로컬 Docker Postgres에서 먼저 dry-run → --apply
  2. 로컬 검증 (수 확인) 통과 후 Supabase 반영

사용:
    ./backend/.venv/bin/python -m scripts.seed_minor_program_rules            # dry-run
    ./backend/.venv/bin/python -m scripts.seed_minor_program_rules --apply    # 실제 upsert

주의:
  - 시드는 upsert(멱등). 두 번 돌려도 신규 0건이어야 함.
  - `courses.course_code`가 없는 경우 program_courses row는 스킵하고 로그만 남긴다.
  - 학번별 분기(curriculum_year) 있는 학과(관광컨벤션·노어노문·지질환경)는 여러 row.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import SessionLocal
from app.domains.academics.models import (
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
)
from app.domains.courses.models import Course


# --- 데이터 구조 -------------------------------------------------------------

@dataclass
class MinorRule:
    academic_program_code: str  # 로그·매칭 편의용 (실제 upsert는 dept/major_id로)
    department_name: str
    major_name: str | None = None  # None이면 학과 자체가 프로그램 단위
    curriculum_year: str | None = None  # 학번별 분기 있으면 "2025" 등
    total_credits: int = 21
    groups: list[dict[str, Any]] = field(default_factory=list)
    exclude_categories: list[str] = field(default_factory=list)
    notes: str | None = None
    # 필수과목 목록 (program_courses에 upsert). (course_code, course_name, group_label)
    courses: list[tuple[str | None, str, str]] = field(default_factory=list)


# --- 학과별 규칙 정의 --------------------------------------------------------
#
# 각 학과의 raw_data/.../00_sources/부전공_요건_수집_*.md 근거.
# code는 raw_data/manual_staging/.../\_pilot_target_list.csv의 academic_program_code.
# name은 실제 courses.course_name 매칭용(공백/괄호 정규화는 upsert 시점에서).

MINOR_RULES: list[MinorRule] = [
    # ---------- 인문대학 ----------
    MinorRule(
        academic_program_code="U01020400001", department_name="고고학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="필수과목 목록은 raw_data md(학과제공, 2026-07-07)에서 확인.",
        courses=[],  # md에 목록 명시. 필요시 채우기.
    ),
    MinorRule(
        academic_program_code="U01020400006", department_name="사학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="필수과목 목록 raw_data md(학과제공).",
    ),
    MinorRule(
        academic_program_code="U01010200008", department_name="국어국문학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="일반 부전공 21학점 (필수 3과목 9학점 + 전공선택 12학점). 교직부전공은 26/35학점.",
        courses=[
            (None, "국어문법론", "필수"),
            (None, "국문학사", "필수"),
            (None, "문예비평론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U01010600018", department_name="영어영문학과",
        groups=[{"label": "택3/7", "type": "min_courses", "n": 3}],
        exclude_categories=["전공기초-영어회화", "전공기초-영어작문"],
        notes="7과목 중 3과목 택. 전공기초 중 영어학입문·영문학입문만 인정, 영어회화·영어작문 불인정.",
        courses=[
            (None, "영미문화의이해", "택3/7"),
            (None, "영문법", "택3/7"),
            (None, "영문학사", "택3/7"),
            (None, "미국문학사", "택3/7"),
            (None, "영어사", "택3/7"),
            (None, "미국희곡", "택3/7"),
            (None, "응용언어학", "택3/7"),
        ],
    ),
    MinorRule(
        academic_program_code="U01010800003", department_name="노어노문학과",
        curriculum_year="2025",
        groups=[{"label": "필수", "type": "all"}],
        notes="2025학년도 이후 교육과정.",
        courses=[
            (None, "초급러시아어문법(II)", "필수"),
            (None, "러시아언어학입문", "필수"),
            (None, "러시아문학입문", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U01010800003", department_name="노어노문학과",
        curriculum_year="pre2025",
        groups=[{"label": "필수", "type": "all"}],
        notes="2025학년도 이전 교육과정.",
        courses=[
            (None, "기초러시아어문법(I)", "필수"),
            (None, "기초러시아어문법(II)", "필수"),
            (None, "러시아문학사", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U01010300010", department_name="일어일문학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="4개 학번 교육과정표(2017/2021/2025-2/2026) 모두 동일 3과목.",
        courses=[
            ("JL2100001", "일본어문법(Ⅰ)", "필수"),
            ("JL2000300", "일본문학개론", "필수"),
            ("JL2000310", "일본어학개론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U01011000004", department_name="불어불문학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="2017 교육과정표 기준.",
        courses=[
            (None, "프랑스문학개론", "필수"),
            (None, "프랑스언어학개론", "필수"),
            (None, "프랑스어강독", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U01010400019", department_name="한문학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="2021/2025 교육과정 가이드 기준.",
        courses=[
            (None, "한문고전의이해", "필수"),
            (None, "한문문법입문", "필수"),
            (None, "한문문학입문", "필수"),
        ],
    ),

    # ---------- 사회과학대학 ----------
    MinorRule(
        academic_program_code="U01020300006", department_name="심리학과",
        groups=[{"label": "택3/7", "type": "min_courses", "n": 3}],
        notes="2023학년도 1학기 시행. 학습심리학 기이수 시 인정(경과조치).",
        courses=[
            (None, "사회심리학", "택3/7"),
            (None, "성격심리학", "택3/7"),
            (None, "심리통계및실습(I)", "택3/7"),
            (None, "과학으로서의심리학", "택3/7"),
            (None, "신경과학입문", "택3/7"),
            (None, "지각심리학", "택3/7"),
            (None, "인지심리학", "택3/7"),
        ],
    ),
    MinorRule(
        academic_program_code="U02030100029", department_name="사회복지학과",
        groups=[{"label": "필수", "type": "all"}],
        exclude_categories=["사회복지현장실습"],
        notes="현장실습 과목은 부전공 이수학점으로 인정 불가.",
        courses=[
            (None, "사회복지실천론", "필수"),
            (None, "사회복지실천기술론", "필수"),
            (None, "사회복지정책론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U02030400005", department_name="사회학과",
        groups=[{"label": "필수", "type": "all"}],
        exclude_categories=["전공기초"],
        notes="2016학년도 2학기부터 사회학과 부전공 학생의 사회학과 전공기초 이수 불허.",
        courses=[
            (None, "사회학사", "필수"),
            (None, "현대사회학이론", "필수"),
            (None, "사회조사방법론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U02030500137", department_name="미디어커뮤니케이션학과",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            (None, "방송미디어론", "필수"),
            (None, "저널리즘의이해", "필수"),
            (None, "커뮤니케이션이론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U02030600012", department_name="정치외교학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="복수전공 요건은 학번별 상이 (2005~2008/2009~2012/2013~2020/2021~).",
    ),
    MinorRule(
        academic_program_code="U01020100006", department_name="문헌정보학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="2025 교육과정표 기준.",
        courses=[
            (None, "장서관리론", "필수"),
            (None, "정보조직론", "필수"),
            (None, "참고정보서비스론", "필수"),
        ],
    ),

    # ---------- 경영대학 ----------
    MinorRule(
        academic_program_code="U02010100035", department_name="경영학과",
        groups=[{"label": "택3/9", "type": "min_courses", "n": 3}],
        exclude_categories=["전공기초"],
        notes="9과목 중 3과목 이수 (2021.12.9자 완화, 2022-1학기부터 적용). 타대교류 학점 1/2까지 인정, 교내 타과 개설 교과목 불인정.",
        courses=[
            ("DB3000711", "재무회계(I)", "택3/9"),
            ("DB3000928", "마케팅관리", "택3/9"),
            ("DB3400701", "오퍼레이션스매니지먼트", "택3/9"),
            ("DB3000932", "재무관리", "택3/9"),
            ("DB3000933", "인적자원관리", "택3/9"),
            ("DB3000924", "투자론", "택3/9"),
            ("DB3100231", "경영정보시스템", "택3/9"),
            ("DB3000927", "관리회계", "택3/9"),
            ("DB3000934", "국제경영학", "택3/9"),
        ],
    ),

    # ---------- 경제통상대학 ----------
    MinorRule(
        academic_program_code="U02010600032", department_name="무역학부",
        groups=[{"label": "필수", "type": "all"}],
        exclude_categories=["전공기초"],
        courses=[
            ("IT3000470", "국제상무론", "필수"),
            ("IT3000512", "국제경제학", "필수"),
            ("IT3000450", "무역영어", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U02030700014", department_name="공공정책학부",
        groups=[{"label": "택3/5", "type": "min_courses", "n": 3}],
        notes="2025학년도 개편. 기 이수분은 부전공 선택으로 인정(경과조치).",
        courses=[
            (None, "공공조직론", "택3/5"),
            (None, "행정법(Ⅰ)", "택3/5"),
            (None, "e-정부론", "택3/5"),
            (None, "공공정책론", "택3/5"),
            (None, "인사정책론", "택3/5"),
        ],
    ),
    MinorRule(
        academic_program_code="U02010300070", department_name="관광컨벤션학과",
        curriculum_year="pre2013",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            (None, "컨벤션산업론", "필수"),
            (None, "관광마케팅", "필수"),
            (None, "문화정책론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U02010300070", department_name="관광컨벤션학과",
        curriculum_year="2013-2016",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            (None, "컨벤션산업론", "필수"),
            (None, "관광마케팅", "필수"),
            (None, "문화산업과 관광", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U02010300070", department_name="관광컨벤션학과",
        curriculum_year="2017",
        groups=[{"label": "필수", "type": "all"}],
        notes="부전공 필수과목 이수 여부는 본인 학번(교육과정 적용 연도) 기준.",
        courses=[
            (None, "컨벤션산업론", "필수"),
            (None, "관광마케팅", "필수"),
            (None, "관광정책론", "필수"),
        ],
    ),

    # ---------- 공과대학 ----------
    MinorRule(
        academic_program_code="U04090100017", department_name="산업공학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="2025 교육과정표 기준. ABEEK 인증학과: 4학년 1학기 전 인증 포기서 제출 필요.",
        courses=[
            (None, "경영과학(I)", "필수"),
            (None, "생산운영관리", "필수"),
            (None, "품질관리론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U04070400012", department_name="재료공학부",
        curriculum_year="2023",
        groups=[{"label": "필수", "type": "all"}],
        notes="2023 교육과정표. ABEEK 인증학과.",
        courses=[
            (None, "재료과학개론(I)", "필수"),
            (None, "재료과학개론(II)", "필수"),
            (None, "열역학(II)", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U04010100003", department_name="건축공학과",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            ("AR2400961", "철근콘크리트구조설계(I)", "필수"),
            ("AR2500608", "건축시공(I)", "필수"),
            ("AR2500657", "건축설비(I)", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U04050100081", department_name="전기전자공학부 전기공학전공",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        notes="전공 21학점 중 ◎ 표시 과목 포함. ABEEK 인증학과.",
        courses=[
            ("ET2500985", "전자기학(II)", "필수"),
            ("ET3500494", "전기회로(II)", "필수"),
            ("ET2001446", "기초전기전자실험", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U04090100007", department_name="사회기반시스템공학과",
        curriculum_year="2025",
        groups=[{"label": "필수", "type": "all"}],
        notes="ABEEK 인증학과. 학번별 ◎ 개수 상이 (3-7개), 여기서는 최대 7과목 명시. 사무실 재확인 권장.",
        courses=[
            (None, "정역학", "필수"),
            (None, "측량학(Ⅰ)", "필수"),
            (None, "유체역학", "필수"),
            (None, "재료역학(Ⅰ)", "필수"),
            (None, "철근콘크리트(Ⅰ)", "필수"),
            (None, "구조역학(Ⅰ)", "필수"),
            (None, "토질역학(Ⅰ)", "필수"),
        ],
    ),

    # ---------- 자연과학대학 ----------
    MinorRule(
        academic_program_code="U05040300016", department_name="물리학과",
        curriculum_year="2025",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            (None, "역학", "필수"),
            (None, "전자기학(I)", "필수"),
            (None, "양자역학(I)", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U05040500023", department_name="지질환경과학과",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        notes="2026 전면개편: 광상학 폐지, 퇴적암석학 신규 지정.",
        courses=[
            ("GY2200775", "구조지질학", "필수"),
            ("GY2200755", "화성암석학", "필수"),
            ("GY3900234", "퇴적암석학", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U05040500023", department_name="지질환경과학과",
        curriculum_year="pre2026",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            ("GY2200775", "구조지질학", "필수"),
            ("GY2200755", "화성암석학", "필수"),
            ("GY2200760", "광상학", "필수"),
        ],
    ),

    # ---------- 사범대학 ----------
    MinorRule(
        academic_program_code="U03050200011", department_name="윤리교육과",
        groups=[{"label": "필수", "type": "all"}],
        notes="2017~2023 교육과정 대상. 전공기초 12학점 + 전공 9학점.",
        courses=[
            (None, "도덕·윤리교육론입문", "필수"),
            (None, "윤리학개론", "필수"),
            (None, "정치와국가윤리", "필수"),
            (None, "서양윤리사상", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050300012", department_name="일반사회교육과",
        curriculum_year="2022-2",
        groups=[{"label": "택3/5", "type": "min_courses", "n": 3}],
        notes="2022학년도 2학기부터 5과목 중 3과목 이수로 확대. 기존 부전공 이수자 전체 소급.",
        courses=[
            (None, "경제학", "택3/5"),
            (None, "정치학", "택3/5"),
            (None, "사회조사와데이터분석", "택3/5"),
            (None, "헌법", "택3/5"),
            (None, "사회과교실수업연구", "택3/5"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050300007", department_name="역사교육과",
        curriculum_year="2024",
        groups=[{"label": "필수", "type": "all"}],
        notes="2024 교육과정 기준. 3과목 모두 교직과정 기본이수과목 겸함.",
        courses=[
            (None, "한국고대사교육", "필수"),
            (None, "서양고대사교육", "필수"),
            (None, "동양중세사교육", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050100002", department_name="국어교육과",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        notes="2026.02.11 교육과정표 기준 ◎ 6과목. 이수 방식(택N/M 여부) 학과사무실 재확인 필요.",
        courses=[
            (None, "국어문법론", "필수"),
            (None, "문학교육론", "필수"),
            (None, "국문학개론", "필수"),
            (None, "의사소통교육론", "필수"),
            (None, "국문학사", "필수"),
            (None, "국어교육론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050500018", department_name="수학교육과",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        notes="2026 교육과정표 ◎ 7과목. 실제 이수 방식 학과사무실 재확인 필요.",
        courses=[
            (None, "수학교육론", "필수"),
            (None, "해석학및지도(I)", "필수"),
            (None, "기하학일반및지도", "필수"),
            (None, "확률과통계및지도", "필수"),
            (None, "현대대수학(I)", "필수"),
            (None, "응용복소해석학(I)", "필수"),
            (None, "위상수학개론", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050500023", department_name="화학교육과",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            (None, "물리화학(I)", "필수"),
            (None, "유기화학(I)", "필수"),
            (None, "분석화학(I)", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050500013", department_name="생물교육과",
        curriculum_year="2025",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            (None, "유전학", "필수"),
            (None, "식물생리학", "필수"),
            (None, "동물생리학", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050100010", department_name="영어교육과",
        curriculum_year="2025",
        groups=[{"label": "필수", "type": "all"}],
        notes="2025 교육과정표 ◎ 6과목. 이수 방식 학과사무실 재확인 필요.",
        courses=[
            ("EG1501185", "영문학개론", "필수"),
            ("EG2800502", "영어학개론", "필수"),
            ("EG2200249", "응용영어음운론", "필수"),
            ("EG2400022", "외국어교수학습론", "필수"),
            ("EG2800550", "영어능력평가", "필수"),
            ("EG2800500", "영어교재연구및지도법", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050300014", department_name="지리교육과",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            ("GE16392", "지도학", "필수"),
            ("GE15946", "지리교육론", "필수"),
            ("GE29302", "지형학", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03010100010", department_name="교육학과",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        notes="2026 교육과정표 ◎ 3과목 (공지에는 6→8과목 확대 언급, 전체 명단 학과 재확인).",
        courses=[
            (None, "한국교육사", "필수"),
            (None, "교육사회학", "필수"),
            (None, "교육통계학", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U03050600009", department_name="체육교육과",
        curriculum_year="2009",
        groups=[{"label": "필수", "type": "all"}],
        notes="2009 교육과정표 기준. 최신 교육과정 재확인 필요.",
        courses=[
            (None, "체육심리", "필수"),
            (None, "운동역학", "필수"),
        ],
    ),

    # ---------- 정보의생명공학대학 ----------
    MinorRule(
        academic_program_code="U04080300126", department_name="정보컴퓨터공학부",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        notes="부모 학부 통합 부전공 규정 명확치 않음. 세부전공별 분기 존재 (컴공/AI/DT). 학과사무실 확인 권장.",
    ),
    MinorRule(
        academic_program_code="U04080100419",
        department_name="정보컴퓨터공학부",
        major_name="컴퓨터공학전공",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        notes="전공기초 중 ◎ 표시 과목만 부전공 인정. 총 21학점.",
        courses=[
            (None, "컴퓨터및프로그래밍입문", "필수"),
            (None, "프로그래밍원리와실습", "필수"),
            (None, "인터넷과웹기초", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U04080100429",
        department_name="정보컴퓨터공학부",
        major_name="인공지능전공",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            (None, "컴퓨터및프로그래밍입문", "필수"),
            (None, "확률통계", "필수"),
            (None, "AI 프로그래밍", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="T00000012652",
        department_name="정보컴퓨터공학부",
        major_name="디자인테크놀로지전공",
        curriculum_year="2026",
        groups=[{"label": "필수", "type": "all"}],
        notes="◎ 2과목 필수 + 전공필수(♤) 중 추가 이수하여 총 21학점.",
        courses=[
            (None, "컴퓨터및프로그래밍입문", "필수"),
            (None, "그래픽기초", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U06040300066", department_name="의생명융합공학부",
        groups=[],  # BME/DS/ABE 세부전공별 분기 — 필수과목 미확인
        notes="세부전공 3개(BME/DS/ABE) 부전공 개설. 필수과목 상세 학과사무실 문의 필요.",
    ),

    # ---------- 생명자원과학대학 ----------
    MinorRule(
        academic_program_code="U04080300412", department_name="IT응용공학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="표준 3필수 대신 4과목 필수(12학점). 잔여 9학점 전공선택에서.",
        courses=[
            (None, "물리학", "필수"),
            (None, "회로이론(I)", "필수"),
            (None, "객체지향프로그래밍", "필수"),
            (None, "디지털공학", "필수"),
        ],
    ),
    MinorRule(
        academic_program_code="U05010300083", department_name="원예생명과학과",
        curriculum_year="2025",
        groups=[{"label": "필수", "type": "all"}],
        courses=[
            ("BH2002333", "채소원예학총론", "필수"),
            ("BH2002334", "과수원예학총론", "필수"),
            ("BH2002332", "화훼원예학총론", "필수"),
        ],
    ),

    # ---------- 생활과학대학 ----------
    MinorRule(
        academic_program_code="U05030300008", department_name="의류학과",
        groups=[{"label": "필수", "type": "all"}],
        notes="의복구성실습은 기존 '의복구성학' 명칭 변경, 구 과목 이수생 인정, 전공기초 '인체와의복설계' 선수강 권장.",
        courses=[
            (None, "의복구성실습", "필수"),
            (None, "패션소재구조학", "필수"),
            (None, "패션디자인발상", "필수"),
        ],
    ),
]


# --- Upsert 로직 -------------------------------------------------------------

def _find_department(db, department_name: str) -> Department | None:
    # 로컬 DB에 이름 중복인 dept가 있을 수 있어(예: 정컴학부 부모 vs 세부전공 편제) first로 관대하게.
    rows = db.execute(select(Department).where(Department.name == department_name).order_by(Department.id)).scalars().all()
    if len(rows) > 1:
        print(f"       ⚠️ dept '{department_name}' 중복 {len(rows)}건, 첫 번째(id={rows[0].id}) 사용")
    return rows[0] if rows else None


def _find_major(db, department_id: int, major_name: str) -> Major | None:
    rows = db.execute(
        select(Major).where(Major.department_id == department_id, Major.name == major_name).order_by(Major.id)
    ).scalars().all()
    return rows[0] if rows else None


def _find_course(db, department_id: int, course_code: str | None, course_name: str) -> Course | None:
    q = select(Course).where(Course.department_id == department_id, Course.course_name == course_name)
    if course_code:
        q = q.where(Course.course_code == course_code)
    rows = db.execute(q.order_by(Course.id)).scalars().all()
    return rows[0] if rows else None


def upsert_rule(db, rule: MinorRule, dry_run: bool) -> dict:
    dept = _find_department(db, rule.department_name)
    stats = {"program": f"{rule.department_name}"
                        + (f"/{rule.major_name}" if rule.major_name else "")
                        + (f"@{rule.curriculum_year}" if rule.curriculum_year else ""),
             "gr_action": "skip", "pc_upserted": 0, "pc_missing": []}
    if not dept:
        stats["gr_action"] = "dept_not_found"
        return stats

    major = None
    if rule.major_name:
        major = _find_major(db, dept.id, rule.major_name)
        if not major:
            stats["gr_action"] = "major_not_found"
            return stats

    special = {"total_credits": rule.total_credits}
    if rule.groups:
        special["groups"] = rule.groups
    if rule.exclude_categories:
        special["exclude_categories"] = rule.exclude_categories
    if rule.notes:
        special["notes"] = rule.notes

    # graduation_requirements upsert
    q = select(GraduationRequirement).where(
        GraduationRequirement.department_id == dept.id,
        # major_id가 None일 때 `== None`은 SQL에서 `= NULL`이 되어 절대 참이 아니다.
        # 그래서 학과 단위 행(major_id IS NULL)은 조회에 안 걸리고 매번 새로 INSERT돼
        # 재실행할 때마다 중복이 쌓였다 — 간호학과 dual 2026 중복(2026-08-13 정리)의
        # 실제 원인이다. is_(None)으로 분기해야 멱등해진다.
        GraduationRequirement.major_id.is_(None)
        if major is None
        else GraduationRequirement.major_id == major.id,
        GraduationRequirement.program_type == "minor",
        GraduationRequirement.curriculum_year == rule.curriculum_year,
    )
    existing = db.execute(q).scalar_one_or_none()
    if existing:
        if existing.special_rules != special or existing.required_total_credits != rule.total_credits:
            stats["gr_action"] = "update"
            if not dry_run:
                existing.special_rules = special
                existing.required_total_credits = rule.total_credits
        else:
            stats["gr_action"] = "unchanged"
    else:
        stats["gr_action"] = "insert"
        if not dry_run:
            db.add(GraduationRequirement(
                department_id=dept.id,
                major_id=major.id if major else None,
                program_type="minor",
                curriculum_year=rule.curriculum_year,
                required_total_credits=rule.total_credits,
                special_rules=special,
            ))

    # program_courses upsert (필수과목 있으면)
    for code, name, group_label in rule.courses:
        course = _find_course(db, dept.id, code, name)
        if not course:
            stats["pc_missing"].append(f"{name} ({code or '-'})")
            continue
        pc_q = select(ProgramCourse).where(
            ProgramCourse.department_id == dept.id,
            # 위와 같은 NULL 비교 함정. program_courses도 학과 단위 행이 134개 있다.
            ProgramCourse.major_id.is_(None)
            if major is None
            else ProgramCourse.major_id == major.id,
            ProgramCourse.course_id == course.id,
            ProgramCourse.curriculum_year == rule.curriculum_year,
        )
        pc_exist = db.execute(pc_q).scalar_one_or_none()
        if pc_exist:
            if pc_exist.requirement_group != group_label:
                if not dry_run:
                    pc_exist.requirement_group = group_label
            continue
        stats["pc_upserted"] += 1
        if not dry_run:
            db.add(ProgramCourse(
                department_id=dept.id,
                major_id=major.id if major else None,
                course_id=course.id,
                requirement_group=group_label,
                curriculum_year=rule.curriculum_year,
            ))
    return stats


def main():
    ap = argparse.ArgumentParser(description="부전공 이수기준 시드")
    ap.add_argument("--apply", action="store_true", help="실제 upsert (기본은 dry-run)")
    args = ap.parse_args()
    dry_run = not args.apply

    db = SessionLocal()
    try:
        all_stats = []
        for rule in MINOR_RULES:
            s = upsert_rule(db, rule, dry_run)
            all_stats.append(s)
            print(f"  [{s['gr_action']:12s}] {s['program']:60s} +courses={s['pc_upserted']:2d}"
                  + (f"  missing={len(s['pc_missing'])}" if s['pc_missing'] else ""))
            if s['pc_missing']:
                for m in s['pc_missing'][:3]:
                    print(f"       └ course not found: {m}")

        if dry_run:
            print(f"\n[DRY-RUN] {len(all_stats)}개 rule 처리. --apply로 실제 반영.")
            db.rollback()
        else:
            db.commit()
            print(f"\n[COMMITTED] {len(all_stats)}개 rule 반영 완료.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

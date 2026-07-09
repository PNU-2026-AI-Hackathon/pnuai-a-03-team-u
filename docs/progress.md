# Plan-U DB Seed Progress

이 문서는 DB seed와 졸업요건 데이터 진행상황의 단일 기록지다. 예전 `docs/db-seed.md`
또는 `docs/progress/*`에 흩어져 있던 내용은 앞으로 이 파일에 모은다.

마지막 업데이트: 2026-07-09

## 원칙

- 2026 현행 학부/전공 계층은 AIS 2026 기준을 따른다.
- `departments`는 학과/학부 단위, `majors`는 학부 아래 세부전공 단위다.
- 전공을 가진 부모 학과를 조회할 때는 `major_id IS NULL` 조건을 반드시 사용한다.
- 폐과/비학부/전문대학원 행은 별표에 졸업학점 기준이 있어도 2026 학부 계층에 임의 추가하지 않는다.
- 이제 DB seed 진행 기록은 이 `docs/progress.md`에만 남긴다.

## 2026 계층 및 과목 seed 완료

2026-07-08 기준 팀 공유 Supabase에 다음 실데이터를 반영했다.

| 테이블 | 행 수 | 내용 |
|---|---:|---|
| `schools` | 1 | 부산대학교 |
| `colleges` | 16 | 현행 단과대 |
| `departments` | 109 | 2026 현행 학과/학부/모집단위 |
| `majors` | 36 | 학부/학과 하위 전공 |
| `courses` | 6,402 | 2026학년도 교육과정 과목 |

소스는 AIS 수강신청/교육과정 응답이다. K2Web 학과 사이트의 교육과정 위젯이 전학교
프록시처럼 동작한다는 점을 이용해 2026 교육과정을 정리했다.

재현 명령:

```bash
cd backend
python -m scripts.seed_school_hierarchy
python -m scripts.import_courses_from_ais
```

시드 원천:

- `backend/seeds/school_hierarchy_mapping.csv`
- `backend/seeds/ais_courses_2026.csv`

중요한 배치 결정:

- 핀테크융합전공은 경영대학 직속이다.
- 지능형헬스사이언스융합전공은 자연과학대학 직속이다.
- EES융합전공은 학부대학 첨단융합학부의 전공이다.
- 첨단융합학부의 현행 전공은 `미래에너지전공`, `나노소자첨단제조전공`,
  `광메카트로닉스공학전공`, `AI융합계산과학전공`, `EES융합전공`이다.
- 별표의 `나노에너지공학과`, `나노메카트로닉스공학과`, `광메카트로닉스공학과`는
  2026 학과분류자료집에서 폐과로 확인되어 라이브 계층에 새 department로 추가하지 않았다.

## 라이브 flat `graduation_requirements` seed

2026-07-09에 라이브 Supabase revision `e5f6a7b8c9d0` 기준으로, 기존 flat
`graduation_requirements` 테이블에 2026 졸업학점 기준을 적재했다.

소스:

- PDF: 「부산대학교 교육과정 편성 및 운영규정」 일부개정규정전문(260225)
- 표 범위: 별표2 page 31-36, 별표2-2 page 38 중 라이브 계층에 존재하는 융합전공
- 전사 CSV: `backend/seeds/graduation_credit_requirements_annex2_2026.csv`
- 라이브 flat 시드 스크립트: `backend/scripts/seed_live_flat_graduation_requirements.py`

현재 라이브 상태:

| 항목 | 행 수 |
|---|---:|
| `graduation_requirements` 전체 | 125 |
| `program_type='primary'` and `curriculum_year='2026'` | 125 |

flat 테이블 컬럼 매핑:

| 별표 원천 | 라이브 컬럼 |
|---|---|
| 총계 | `required_total_credits` |
| 전공필수 | `required_major_required` |
| 전공선택 + 심화전공 | `required_major_elective` |
| 효원핵심교양 | `required_general_required` |
| 효원균형교양 + 효원창의교양 | `required_general_elective` |
| 일반선택 | `required_free_elective` |

삽입 결과:

- 별표2 page 31-36 중 2026 라이브 계층에 매칭되는 123행 삽입.
- 별표2-2 page 38 중 라이브 계층에 매칭되는 2행 추가 삽입.
  - 자연과학대학 `지능형헬스사이언스융합전공`
  - 경영대학 `핀테크융합전공`
- 중복 행 없음 확인.

대표 확인값:

| 프로그램 | 총계 | 전필 | 전선+심화 | 교양필수 | 교양선택 | 일반선택 |
|---|---:|---:|---:|---:|---:|---:|
| 국어국문학과 | 126 | 18 | 39 | 9 | 21 | 27 |
| 국어교육과 | 135 | 24 | 38 | 9 | 18 | 12 |
| 의학과 | 174 | 141 | 33 |  |  |  |
| 전기전자공학부 전기공학전공 | 137 | 36 | 45 | 10 | 15 | 6 |
| 첨단융합학부 미래에너지전공 | 137 | 36 | 45 | 10 | 15 | 6 |
| 첨단융합학부 나노소자첨단제조전공 | 137 | 36 | 45 | 10 | 15 | 6 |
| 첨단융합학부 광메카트로닉스공학전공 | 137 | 36 | 45 | 10 | 15 | 6 |
| 첨단융합학부 AI융합계산과학전공 | 137 | 39 | 39 | 10 | 15 | 9 |
| 지능형헬스사이언스융합전공 | 126 | 21 | 42 | 9 | 21 | 15 |
| 핀테크융합전공 | 126 | 12 | 60 | 9 | 18 | 21 |

라이브 계층에 매칭하지 않은 별표 행:

- 폐과 학부 행: `나노에너지공학과`, `나노메카트로닉스공학과`, `광메카트로닉스공학과`,
  `식물생명과학과`, `동물생명자원과학과`
- 라이브 현행 학부 계층에 없는 행: `치의학전문대학원 학석사통합과정 학사과정`,
  `한의학전문대학원 학석사통합과정 학사과정`
- 라이브 계층 미존재 융합전공: `미래자동차융합전공`
- `의생명융합공학부 첨단바이오공학전공`은 별표에는 있으나 라이브 `majors`에 없어 미반영.
  현행 전공으로 유지할지 여부를 별도 확인해야 한다.

재실행 방법:

```bash
cd backend

# page 31-36 별표2 기준, 기존 primary/2026 flat 요건 교체
python -m scripts.seed_live_flat_graduation_requirements --replace --apply

# page 38 별표2-2 중 라이브 계층에 있는 융합전공만 추가/갱신
python -m scripts.seed_live_flat_graduation_requirements --only-annex2-2 --apply
```

스크립트는 같은 `(program_type, curriculum_year, department_id, major_id)` 행을 먼저 지우고
다시 넣기 때문에 재실행해도 중복을 만들지 않는다.

## 새 졸업요건 스키마 작업 상태

브랜치: `feat/graduation-requirement-schema`

새 스키마는 flat `graduation_requirements`를 장기적으로 대체하기 위한 작업이다. 라이브 DB에는
아직 적용하지 않았다.

핵심 결정:

- 부전공/복수전공은 `requirement_sets.program_type`으로 표현한다.
- 교직은 program_type이 아니며 primary 요건세트의 카테고리로 표현한다.
  - `teacher_training_basic`
  - `teacher_training_pedagogy`
- 대학 공통 기본규칙은 `requirement_sets.scope='university_default'` 행으로 둔다.
- 부전공/복수전공 미제공 학과는 `offering_status='not_offered'`로 표현한다.
- 택N/M 조건은 `requirement_condition_groups`와 `requirement_condition_group_courses`로 표현한다.

신규 마이그레이션:

1. `a1c3e5b7d9f2` - `academic_programs`, aliases, departments/majors bridge
2. `b2d4f6a8c0e3` - `requirement_sets`, `requirement_categories`, `requirement_courses`
3. `c3e5a7b9d1f4` - 조건그룹 2테이블
4. `d4f6b8c0e2a5` - `user_academic_programs.academic_program_code`
5. `e5a7c9d1f3b6` - flat `graduation_requirements` drop

검증:

- 빈 DB에서 `alembic upgrade head` 성공
- `alembic downgrade f7a8b9c0d1e2` 후 `upgrade head` 왕복 성공
- `alembic check` drift 0
- 골든테스트 TC01-TC10 통과

## 남은 일

- `의생명융합공학부 첨단바이오공학전공`을 2026 현행 계층에 포함할지 확인.
- live flat 테이블과 새 `requirement_sets` 스키마 중 PR 범위를 명확히 정리.
- 부전공/복수전공/교직 세부 요건 seed는 아직 완성 전이다.
- 새 스키마를 Supabase에 적용할 경우, live flat `graduation_requirements`를 drop하기 전에
  현재 125행의 졸업학점 기준을 `requirement_categories`로 이전하는 경로가 필요하다.

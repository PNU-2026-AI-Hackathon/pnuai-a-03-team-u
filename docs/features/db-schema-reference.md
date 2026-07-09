# DB 스키마 레퍼런스 (컬럼별 의미)

2026-07-09 기준, 브랜치 `feat/graduation-requirement-schema` (마이그레이션
`e5a7c9d1f3b6`까지). 모든 테이블은 별도 표기 없으면 `TimestampMixin`의
`created_at`/`updated_at`을 가진다. 졸업요건 영역(academic_programs / requirement_*)은
스키마만 반영된 상태고 **시드는 아직**이다(다음 세션) — "행 수"로 적힌 값은 codex 브랜치
로컬 파이프라인 실측치로, 재시드 시 기준치 참고용.

## 계층 (회원가입/조회용 이름 계층)

`schools → colleges → departments → majors`. AIS 편제 기준으로 시드됨
(라이브: colleges 16 / departments 109 / majors 36 — `docs/CHANGELOG.md`의 최신 DB seed 항목).
**학과 단위 조회는 `major_id IS NULL` 필터 필수** — 학부제 부모 학과 14곳은
department_id만으로 조회하면 하위 전공 행이 섞인다.

### departments
| 컬럼 | 의미 |
|---|---|
| college_id | colleges FK. UNIQUE(college_id, name) |
| name | 학부/학과명("의생명융합공학부", "컴퓨터공학과") |
| academic_program_code | **신규** — academic_programs 브리지 FK(nullable). 코드가 세부 전공(majors) 쪽에만 있는 학부제 케이스는 null. 부분 unique 인덱스 |

### majors
| 컬럼 | 의미 |
|---|---|
| department_id | departments FK. UNIQUE(department_id, name) |
| name | 세부 전공명("데이터사이언스전공"). 학과=전공 단위면 행 없음(참조측 major_id null) |
| academic_program_code | **신규** — 브리지 FK(nullable, 부분 unique) |

## 사용자 영역

### users — 서비스 계정
| 컬럼 | 의미 |
|---|---|
| email / password_hash / name / student_id | 로그인 ID(unique) / bcrypt / 이름 / 학번(unique) |
| department_id / major_id | 소속 계층 FK (가입 입력 검증 + 학적부 크롤링 갱신) |
| career_goal | 희망 진로 텍스트 |
| advisor_consulted | 지도교수 상담 여부 |

### portal_credentials — 학교 포털 계정 (크롤링용)
user_id unique(1인 1계정), portal("pnu_onestop"), login_id, encrypted_password
(`encrypt_secret()` 암호화 — 평문 저장 금지 원칙).

### user_academic_programs — 사용자의 학적 프로그램 (주/복수/부전공)
| 컬럼 | 의미 |
|---|---|
| user_id | users FK |
| department_id / major_id | 프로그램의 소속 계층 FK (portal-sync가 이름 매칭으로 채움) |
| academic_program_code | **신규** — academic_programs FK(nullable). **엔진이 요건세트를 찾는 키.** portal-sync/가입 시 department/major의 브리지 컬럼에서 resolve해 채운다(엔진 어댑테이션은 후속 작업 — 현재는 미채움) |
| program_type | primary / dual / minor / interdisciplinary (auth `_VALID_PROGRAM_TYPES`, 크롤러 라벨 매핑과 일치). **교직은 program_type이 아님** — 아래 requirement_categories 참고 |
| curriculum_year | 교육과정 적용년도(학적부 크롤링). 요건세트 연도 매칭에 사용 |
| status | active 등 학적상태. 엔진은 active만 평가 |

### student_course_records — 이수 과목 기록 (성적표)
| 컬럼 | 의미 |
|---|---|
| user_id / course_id | users FK / courses FK(nullable — 카탈로그 매칭 성공 시만. 타학과 과목 필터가 이 FK에 의존) |
| user_academic_program_id | 이 과목이 어느 프로그램 요건으로 카운트되는지(nullable). 성적표 원본엔 없어 판정 로직이 나중에 채움 |
| raw_course_code / raw_course_name | 성적표 원문 그대로 |
| category | 이수구분 원문("전공필수", "교양", "교직과목" 등). 엔진이 `RAW_CATEGORY_TO_CODES`로 코드 매핑해 학점 합산 |
| credits / year / semester / grade / grade_point / is_retake | 학점/연도/학기/등급/평점/재수강 |
| match_status / source | courses 매칭 상태 / 출처(기본 "crawler") |

## 참조 데이터 (마스터)

### academic_programs — 학사 프로그램 마스터 (151개 예정, 졸업요건의 기준 단위)
| 컬럼 | 의미 |
|---|---|
| academic_program_code | PK. "U05040300016" 형태 — 요건/교육과정 연결의 전역 키 |
| program_name / normalized_program_name | 정식명 / 이름 매칭용 정규화 문자열(인덱스) |
| college_name / parent_department_name / major_name | 소속 단과대 / 상위 학부 / 세부 전공명 |
| survey_* / campus_* / day_night_* / duration_* / status_* / kedi_* 등 | KEDI/AIS 조사 원본 메타(대부분 코드 미사용 — 출처 증빙용) |
| is_active / is_bachelor | 운영 여부 / 학사과정 여부 — 시드·조회 필터 |

계층과의 연결은 `departments.academic_program_code` / `majors.academic_program_code`
브리지 컬럼(위 참고)이 담당한다.

### academic_program_aliases — 프로그램명 별칭 (이름→코드 해석)
academic_program_code FK / alias_type / alias_name / normalized_alias_name / source.
UNIQUE(code, type, name). 가입·portal-sync의 코드 resolve 창구가 될 예정.

### courses — 수강편람 과목 카탈로그 (6,402행 시드됨)
| 컬럼 | 의미 |
|---|---|
| course_code / course_name | 과목코드 / 과목명 |
| department_id / major_id | 개설 주체 계층 FK. 교양과목은 department_id=NULL 컨벤션 |
| category | 이수구분 태그(카탈로그 기본값 — 학과별 요건 아님) |
| credits / year / semester | 학점 / 처음 확인된 개설 학년·학기(참고값) |

개설 실체(학기/분반/교수/시간)는 `course_offerings` / `course_times`.

## 졸업요건 (이 브랜치에서 재설계된 영역)

### requirement_sets — 요건세트: (프로그램, 이수유형, 적용년도)당 1행
| 컬럼 | 의미 |
|---|---|
| scope | `program`(기본) / `university_default`. **university_default + code NULL 행 = 학사운영규정의 대학 공통 기본규칙**(부전공 21학점/필수 9학점, 복수전공=최소전공소계). 프로그램별 행이 없으면 엔진이 이걸로 폴백(후속 작업). CHECK: (scope='program') = (code IS NOT NULL) |
| academic_program_code | 어느 프로그램의 요건인지(정본 키). UNIQUE(code, type, year). default 행 중복은 부분 인덱스 `uq_requirement_sets_default`가 방지 |
| department_id / major_id | 계층 FK(시드가 브리지 매칭으로 채움). 엔진 타학과 필터의 FK 비교 경로. 학과 단위 조회는 major_id IS NULL 필수 |
| program_type | primary / dual / minor / interdisciplinary. **부전공·복수전공 요건은 별도 테이블이 아니라 이 타입 값으로 구분** |
| curriculum_year | 적용 교육과정 연도 |
| offering_status | `offered`(기본) / `not_offered` — **규정상 부전공/복수전공 불가 학과(37개)를 명시하는 행**. offering_note에 근거 규정 |
| required_total_credits / rule_metadata / is_active | 졸업 총 이수학점 / 출처·증빙 JSONB / 활성 여부(엔진은 active만) |

### requirement_categories — 카테고리별 학점/규칙
| 컬럼 | 의미 |
|---|---|
| external_id | 시드 파이프라인 안정 키(unique) — 재시드해도 같은 행 유지 |
| requirement_set_id | 소속 세트 FK(CASCADE). 프로그램 식별은 전부 이 FK로 따라감 |
| category_code | major_required / major_elective / major_foundation / deep_major / general_total / free_elective / **minimum_major_total**(전기+전필+전선 합산 집계 — 복수·부전공 총량) / **teacher_training_basic**(교직 △ 기본이수) / **teacher_training_pedagogy**(교직 □ 교과교육 ≥8학점) 등 |
| category_name / minimum_credits | 표시명 / 최소 학점(자유 텍스트 — 파싱은 엔진) |
| rule_type | `minimum_credits`(학점 기준) / `required_courses`(과목 체크리스트) / `aggregate_min_major_total` / **`manual_check`**(적성검사 등 성적표로 판정 불가한 요건 — 엔진이 satisfied=None으로 노출) |
| source_kind / source_file / needs_review / review_reason / notes | 출처/검토 상태. **엔진은 needs_review=false만 사용** |

### requirement_courses — 요건세트에 연결된 과목 행
stash 정리본과 동일: external_id(unique) / requirement_set_id(CASCADE) /
curriculum_year(행 단위 적용년도) / category_code(`MANDATORY_COURSE_CATEGORIES` =
전필·전기·교필·**교직기본이수**면 개별 필수과목 판정, 그 외는 메뉴형) /
recommended_year·semester(로드맵 원료) / raw_* (원문 보존) /
matched_course_code·name(카탈로그 매칭 — "A|B" 파이프는 택1 대체과목, 엔진 인식) /
match_status·method·terms·departments / choice_rule_types·raw(있으면 개별 필수 판정 제외) /
source_table(**department_courses_from_catalog는 영구 needs_review**) / source_file /
needs_review·review_reason.

### requirement_condition_groups — 택N/M 이수 조건 그룹 (**신규**)
"부전공필수 9과목 중 3과목 선택" 같은 조건. 부전공에서 출발했지만 전 program_type 공통.
| 컬럼 | 의미 |
|---|---|
| external_id | canonical CSV condition_group_id(unique) |
| requirement_set_id / category_code | 소속 세트 FK(CASCADE) / 관련 카테고리 |
| condition_type | `choose_at_least_n_courses` 등 |
| group_name / rule_summary / source_text | 표시명 / 규칙 요약 / 원문("택3/9" 프로즈, 중복인정·경과조치 비고 포함) |
| min_courses / min_credits / max_courses / max_credits / excess_allowed | 최소·최대 과목수/학점, 초과 인정 여부 |
| needs_review / review_reason / notes | 검토 상태 |

### requirement_condition_group_courses — 조건 그룹의 후보 과목 (**신규**)
condition_group_id FK(CASCADE) / course_role(`candidate`/`required`/`excluded`) /
raw_course_name / course_code(파이프 구분 대안 보존, TEXT) / course_name / credits /
category_code / match_status / recognition_status / source_note.
행 unique 없음 — 원본 CSV에 행 키가 없어 시드는 그룹 단위 delete-and-reinsert.

### 삭제된 테이블
- `graduation_requirements`(flat 스텁) — 코드 참조 0, 빈 테이블. requirement_sets가 대체
  (`e5a7c9d1f3b6`에서 drop).
- codex 브랜치의 `department_academic_program_mappings` / `graduation_audits` /
  `graduation_audit_program_results` / `requirement_text_rules`는 main으로 포팅하지 않음
  (읽는 코드 0 또는 폐기 결정 — `docs/CHANGELOG.md`의 졸업요건 스키마 재설계 항목).

## 비교과 활동 / 기타

- `activities`: 크롤링된 비교과 공고(pgvector 임베딩 + IVFFlat 인덱스).
- `user_activities`: 외부활동+공모전 통합(2026-07-08, PR #48/#50 라인).
- `user_certifications` / `user_language_scores`: 자격증/어학성적.
- `academic_info_articles`, `course_plans`/`course_plan_items`,
  `course_roadmaps`/`course_roadmap_items`: content/planning 도메인 — 이번 재설계 무관.

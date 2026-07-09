# Supabase 졸업요건 스키마 반영 계획 (요약)

2026-07-09, blackest21. 상세 설계 근거는
[graduation-requirement-schema-redesign.md](graduation-requirement-schema-redesign.md) 참고.
이 문서는 "Supabase에 뭐가 새로 생기고, 어떻게 반영하는지"만 요약한다.

## 한 줄 요약

**테이블을 수동으로 만들지 않는다.** 브랜치 `feat/graduation-requirement-schema`의
Alembic 리비전 5개를 `alembic upgrade head` **1회 실행**으로 반영한다.
데이터(시드)는 그 다음 단계 — 이번 반영으로는 빈 테이블만 생긴다.

## 현재 상태

| 항목 | 상태 |
|---|---|
| 라이브 Supabase 리비전 | `e5f6a7b8c9d0` (d0won 로드맵 스냅샷까지 반영됨) |
| 브랜치 리비전 체인 | `e5f6a7b8c9d0 → a1c3e5b7d9f2 → b2d4f6a8c0e3 → c3e5a7b9d1f4 → d4f6b8c0e2a5 → e5a7c9d1f3b6` |
| 로컬 검증 | 빈 DB 전체 체인 upgrade / downgrade 왕복 / `alembic check` drift 0 / 골든테스트 10개 통과 |

## Supabase에 생기는 변화

### 신규 테이블 7개 (전부 빈 상태로 생성)

| 테이블 | 역할 |
|---|---|
| `academic_programs` | 학사 프로그램 마스터(151개 예정, AIS 코드 기준) — 졸업요건의 기준 단위 |
| `academic_program_aliases` | 프로그램명 별칭(이름→코드 해석) |
| `requirement_sets` | (프로그램 × 이수유형 × 연도)별 요건세트. 부전공/복수전공=program_type 행, 대학 공통 기본규칙=scope='university_default' 행, 미제공 학과=offering_status='not_offered' 행 |
| `requirement_categories` | 카테고리별 학점/규칙(전필·전선·교양·교직 △/□ 등) |
| `requirement_courses` | 요건세트에 연결된 과목 행(필수과목, 택1 파이프) |
| `requirement_condition_groups` | 택N/M 조건 그룹("9과목 중 3과목", 균형교양 "6영역 중 5" 등) |
| `requirement_condition_group_courses` | 조건 그룹의 후보/필수/제외 과목 |

### 기존 테이블 변경 3개 (컬럼 추가만, 데이터 무손실)

- `departments` · `majors` · `user_academic_programs`에 `academic_program_code` 컬럼 추가
  (계층 ↔ 졸업요건 브리지, nullable FK — 기존 행에 영향 없음)

### 삭제 1개

- `graduation_requirements` — flat 스텁. **라이브에서 0행·코드 참조 0** 확인 완료.
  requirement_sets가 대체.

### 교양 관련

새 테이블 없음 — 핵심교양은 `requirement_courses`, 균형/창의 소영역은
`requirement_condition_groups`, 학점 기준은 `requirement_categories`로 전부 수용.

## 반영 절차 (팀 승인 후)

1. PR 리뷰/머지 (`feat/graduation-requirement-schema`)
2. 로컬 Postgres에서 최종 리허설: 빈 DB `alembic upgrade head` + 골든테스트
3. Supabase에 1회 실행: `cd backend && alembic upgrade head` (.env의 실제 DATABASE_URL)
4. 확인: `alembic current` = `e5a7c9d1f3b6`, 신규 테이블 7개 존재, 기존 행 수 변화 없음

문제 시 롤백: `alembic downgrade e5f6a7b8c9d0` (신규 5개 전부 downgrade 지원,
이 시점엔 빈 테이블이라 무손실).

## 이번에 하지 않는 것 (다음 단계)

- **시드**: academic_programs 151개, 별칭, 브리지 backfill, 학과별 요건세트/카테고리/
  과목/조건그룹 적재 (부전공 확정 34개 학과, 미제공 37개 학과, 교직 마커, 교양 이수모형)
- **엔진 확장**: 기본규칙 폴백, not_offered 판정, 교직 매핑, 택N/M 판정
- **교양 실과목→소영역 매핑** 데이터 확보 (수강편람 확인 중)

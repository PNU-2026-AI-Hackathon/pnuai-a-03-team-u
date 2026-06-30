# Plan-U Backend, DB, and Infra Architecture

## Purpose

This document records the backend, database, and deployment direction agreed for Plan-U before implementation starts.

The current goal is not to implement business logic yet. The goal is to keep the repository structure aligned with the product architecture so that later API, database, and deployment work can be added without mixing responsibilities.

## Scope Decision

Frontend work is owned separately. This architecture focuses on:

- Backend API
- PostgreSQL and pgvector database design
- Graduation requirement engine
- Course catalog and timetable data
- RAG and LLM integration boundaries
- Data ingestion from CSV and crawlers
- Docker, EC2, RDS, Nginx, and GitHub Actions deployment

## Architecture Fit Review

The first backend layout split every future domain into a top-level package. That was directionally correct, but too noisy for MVP development because model files, crawlers, RAG, LLM calls, and graduation logic were spread across many sibling folders before the implementation was large enough to need that much separation.

The revised layout keeps the important boundaries but folds related work into fewer top-level packages:

- `domains` owns product data and deterministic business rules.
- `ingestion` owns external data collection, parsing, and normalization.
- `ai` owns shared RAG, embedding, LLM, prompt, and recommendation support.
- `api` owns FastAPI router assembly.
- `core` owns settings, DB, security, shared dependencies, and common utilities.

This keeps the agreed principle intact: AI must not decide graduation satisfaction. Deterministic domain logic performs graduation audits, while `app/ai` explains, searches, embeds, and drafts recommendation text based on validated data.

## Backend Structure

```text
backend/
  app/
    core/
    api/
    domains/
      users/
      academics/
      courses/
    ingestion/
      csv_importers/
      crawlers/
      parsers/
      normalizers/
    ai/
      rag/
      llm/
      embeddings/
      prompts/
      recommendations/
  migrations/
  scripts/
  seeds/
  tests/
```

### Module Responsibilities

`core`
- Settings, database session, security helpers, common exceptions, and shared dependencies.

`api`
- FastAPI router assembly, versioned API entry points, and health routes.

`domains/users`
- Email and password authentication for MVP.
- JWT issuance and user identity APIs.
- Designed so Google, Kakao, and Naver OAuth can be added later through provider accounts.
- User consent and portal credential ownership should live here.

`domains/academics`
- User academic programs: primary major, dual major, minor, interdisciplinary major.
- Completed course records.
- Certifications, language scores, competitions, and activities.
- CSV/manual course record input comes first. OCR can be added later.
- Graduation requirement sets by school, department, major, program type, and curriculum year.
- Requirement categories, required courses, equivalency rules, prerequisite rules, and overlap rules.
- Calculates graduation audit results from user course records and curriculum rules.
- MVP calculates each selected program independently.
- Later versions can add integrated overlap handling across primary, dual, minor, and interdisciplinary programs.

`domains/courses`
- Courses, course offerings, sections, professors, capacity, and timetable blocks.
- MVP data can be imported from CSV.
- Later crawlers should upsert into the same normalized tables.

`ingestion`
- `csv_importers`: MVP importers for course records and course offerings.
- `crawlers`: crawlers for course catalog, student portal data, academic notices, campus opportunities, and department requirement sources.
- `parsers`: text extraction or LLM-assisted parse candidates.
- `normalizers`: conversion into stable DB-ready records.

`ai/rag`
- Documents and chunks for academic information, graduation source documents, course guide documents, campus extracurricular opportunities, and internal competitions.
- Uses pgvector once embeddings are enabled.
- Used for search and chatbot context, not for final graduation judgment.

`ai/llm`
- GPT/Claude client wrappers.
- Prompt templates for explaining audit results and recommendation reasons.
- Receives de-identified or minimal data.

`ai/recommendations`
- Recommendation support that depends on validated domain data.
- Deterministic filtering should stay in `domains`; LLM-facing explanation and ranking support can live here.

## Authentication Direction

Decision:

- Design for email/password plus future social login.
- Implement email/password first.
- Add OAuth later through provider accounts.

Recommended tables:

```text
users
- id
- email
- password_hash
- name
- student_id
- school
- department
- career_goal
- created_at
- updated_at
```

```text
auth_accounts
- id
- user_id
- provider          # local/google/kakao/naver
- provider_user_id
- email
- created_at
```

## Database Direction

The database should use normalized tables for core audit logic and JSONB for program-specific exceptions or source metadata.

Reason:

- Graduation audits need deterministic, queryable data.
- PNU departments can have complex exceptions that are difficult to model perfectly at first.
- JSONB lets us preserve special cases without blocking the normalized MVP.

### Core Academic Profile

```text
user_academic_programs
- id
- user_id
- requirement_set_id
- school
- department
- major
- program_type        # primary/dual/minor/interdisciplinary
- curriculum_year
- status              # active/completed/dropped
```

```text
student_course_records
- id
- user_id
- course_id
- raw_course_code
- raw_course_name
- category
- credits
- year
- semester
- grade
- grade_point
- is_retake
- match_status        # matched/unmatched/needs_review
- source              # manual/csv/ocr
```

### Curriculum and Graduation Requirements

```text
requirement_sets
- id
- school
- department
- major
- program_type
- curriculum_year
- name
- required_total_credits
- rule_metadata       # JSONB
- is_active
```

```text
requirement_categories
- id
- requirement_set_id
- category
- required_credits
- min_courses
- rule_metadata       # JSONB
```

```text
requirement_courses
- id
- requirement_set_id
- category
- course_id
- requirement_type    # required/choose_one_of/optional_group
- group_key
- min_select_count
- rule_metadata       # JSONB
```

```text
course_equivalencies
- id
- source_course_id
- equivalent_course_id
- rule_type
- rule_metadata       # JSONB
```

```text
course_prerequisites
- id
- course_id
- prerequisite_course_id
- rule_metadata       # JSONB
```

```text
program_overlap_rules
- id
- school
- primary_program_type
- secondary_program_type
- rule_type
- max_overlap_credits
- rule_metadata       # JSONB
```

### Course Catalog and Timetable

```text
courses
- id
- school
- course_code
- course_name
- department
- major
- default_category
- credits
```

```text
course_offerings
- id
- course_id
- school
- year
- semester
- section
- source_type             # manual_xlsx/onestop_json/onestop_excel/admin
- source_name             # original file name or source URL
- source_snapshot_date    # date shown by a static source file, nullable
- crawled_at              # time when live crawler collected this row, nullable for manual files
- first_seen_at
- last_seen_at
- offering_status         # active/cancelled/cancelled_candidate/new_candidate/changed/archived
- change_status           # unchanged/added/removed/modified/needs_review
- change_checked_at
- professor
- capacity
- enrolled_count
- grade_level
- campus
- class_type
- is_online
- remark
```

```text
course_times
- id
- offering_id
- day_of_week
- start_time
- end_time
- classroom
```

### Course Catalog Import Standard

Course catalog import should use the 2026 undergraduate course offering file as the canonical column format.

Canonical 2026 column mapping:

```text
주관대학명        -> college
학과(부)          -> parent_department
주관학과코드      -> offering_department_code
주관학과명        -> offering_department
학년              -> target_grade
교과목번호        -> course_code
분반              -> section
교과목명          -> course_name
교과목구분        -> category
학점              -> credits
이론시간          -> lecture_hours
실습시간          -> practice_hours
시간표            -> timetable_raw
교수명            -> professor
교양영역명        -> general_education_area
원어강의          -> foreign_language_lecture
팀티칭            -> team_teaching
원격강좌여부      -> is_remote
```

Older course catalog files should be normalized into the 2026 naming standard through header aliases.

Known aliases:

```text
대학명            -> 주관대학명
상위소속(학과)    -> 학과(부)
교과목코드        -> 교과목번호
교과구분          -> 교과목구분
제한인원          -> 수강제한인원
수강제한인원      -> capacity
```

The display name for undergraduate departments should preserve both the parent school/department and the concrete major or offering department.

Example:

```text
parent_department: 정보컴퓨터공학부
major: 컴퓨터공학전공
display_department_name: 정보컴퓨터공학부 컴퓨터공학전공
```

Graduation requirement calculation should still use the concrete requirement set linked to the student's selected program, not only the display name.

Department and program names can change across curriculum years, so graduation requirements should not rely on names as stable identifiers.

Plan-U should use the 2026 department/major classification workbook as the primary academic program master source. This source includes department code, department name, college code, college name, degree type, department status, first recruitment year, and source updated time. The older KEDI standard classification file should not be used as the primary master because it does not describe the 2026 program transition as cleanly.

Onestop course catalog JSON includes `MNG_DEPT_CD`, which should be stored as `offering_department_code` and mapped as an external source key, not as the primary academic program key.

Recommended program identity tables:

```text
academic_programs
- id
- school
- program_code          # stable internal code used by Plan-U, seeded from 2026 classification 학과코드 when possible
- source_department_code
- current_name
- program_type          # department/major/dual_major/minor/interdisciplinary/linked/free_major
- college_code
- current_college
- degree_type
- status                # active/renamed/merged/split/closed
- source_status         # 기존/신설/변경/폐과
- first_recruitment_year
- source_updated_at
- effective_from_year
- effective_to_year
```

```text
academic_program_external_ids
- id
- academic_program_id
- source_system         # onestop/course_catalog/manual
- external_id           # e.g. MNG_DEPT_CD
- external_name
- valid_from_year
- valid_to_year
```

```text
academic_program_aliases
- id
- academic_program_id
- alias_name
- alias_type            # old_name/display_name/source_name
- valid_from_year
- valid_to_year
```

If a program is renamed but graduation requirements continue, keep the same `academic_program_id` and add a new alias/external-id validity row. If a program is split, merged, or moved to another college with different requirements, create a new `academic_program_id` and link it through a transition table.

Course identity and offering identity should be handled separately:

```text
course identity:
- school
- course_code

offering identity:
- school
- course_code
- year
- semester
- section
```

Timetable parsing should preserve the original timetable text and store parse status.

```text
course_offerings.timetable_raw
course_offerings.timetable_parse_status  # parsed/partial/needs_review
```

Parsed timetable rows should be inserted into `course_times` only when reliable. If parsing fails, keep the raw timetable text and mark the row for review.

Course offerings should keep source and change-tracking metadata because static course catalog files and live Onestop crawler results can represent different points in time.

Recommended status rules:

```text
manual snapshot has row, latest crawler has row, values same      -> active / unchanged
manual snapshot has row, latest crawler has row, values changed   -> changed / modified
manual snapshot has row, latest crawler does not have row         -> cancelled_candidate / removed
manual snapshot does not have row, latest crawler has row         -> new_candidate / added
review confirms cancellation                                  -> cancelled / removed
```

The system should not automatically treat every missing live row as final cancellation. It should first mark it as `cancelled_candidate` because differences may also come from source timing, category filters, endpoint behavior, or temporary Onestop changes.

Course registration restrictions should be modeled separately because one offering can have multiple department, grade, nationality, academic status, or degree-program restrictions.

Recommended table:

```text
course_registration_restrictions
- id
- offering_id
- school
- year
- semester
- course_code
- section
- restriction_type
- allowed
- target_department
- target_grade
- nationality
- academic_year
- completed_semesters
- academic_status
- degree_program
- reason
- raw_metadata       # JSONB
```

### Graduation Audit Results

The audit API should calculate from the latest data. Saved snapshots are useful when a student wants to preserve a semester planning state.

```text
graduation_audits
- id
- user_id
- audit_year
- audit_semester
- status
- summary_json
- created_at
```

```text
graduation_audit_program_results
- id
- audit_id
- user_academic_program_id
- requirement_set_id
- result_json
```

The response shape should include:

- Integrated summary
- Per-program audit results
- Missing required courses
- Remaining credits by category
- Warnings for unresolved overlap or unmatched records

## Data Ingestion Direction

### MVP

- Graduation requirements are entered as curated seed data first.
- Course catalog and timetable data are imported from CSV.
- Student completed courses are imported from CSV and can be manually edited.
- OCR is deferred until the CSV/manual flow is stable.

### Later Expansion

- Course catalog crawler runs every semester.
- Department graduation requirement crawler collects source documents.
- Graduation requirement parsing produces review candidates, not direct production rules.
- A human review step approves parsed candidates before they are applied to `requirement_sets` and related rule tables.

### Course Catalog Crawler Plan

The planned course catalog crawler source is:

```text
https://onestop.pusan.ac.kr/page?menuCD=000000000000335
```

Crawler input selections:

```text
학년도/학기: target academic year and semester
대학/대학원: 대학
과목구분: iterate across available course category values
```

The crawler should export or collect CSV files for each course category, then normalize and join those category-specific files into the canonical course catalog schema.

Recommended flow:

```text
Onestop page
-> select 학년도/학기
-> select 대학
-> iterate 과목구분
-> export CSV per category
-> store raw CSV under ignored raw_data/crawled_data during local experiments
-> normalize headers to 2026 canonical names
-> join/deduplicate by school + course_code + year + semester + section
-> compare latest live crawl with the static source snapshot
-> mark active, changed, new_candidate, and cancelled_candidate rows
-> load into courses, course_offerings, course_times, and course_registration_restrictions
```

The crawler should not bypass normalization. It should produce the same normalized shape as the MVP CSV import path so that manual files and crawled files share one ingestion pipeline.

Initial crawler script:

```text
backend/app/ingestion/crawlers/onestop_course_catalog.py
```

Example command:

```bash
python3 backend/app/ingestion/crawlers/onestop_course_catalog.py \
  --year 2026 \
  --semester 1 \
  --subject-categories 1 2 3 4 5 \
  --output-dir raw_data/crawled_data/onestop_course_catalog/2026_1
```

The crawler currently:

- opens the Onestop course catalog page
- extracts the page RSA public key and CSRF token
- mirrors the client-side encrypted AJAX request format
- fetches each selected subject category
- stores raw JSON by category
- writes a normalized 2026-format course catalog CSV
- can optionally call the course precaution endpoint with `--include-precautions`

Precaution crawling can create thousands of extra requests, so experiments should use `--precaution-limit` first.

Known limitation:

- The Onestop JSON endpoint does not currently return the same college and parent-department columns present in some downloaded Excel files. Those fields remain blank unless later enriched from another source.
- A downloaded course catalog file is a snapshot, while the live JSON endpoint can include later changes such as added sections, changed professors, changed classrooms, or cancellation rounds. Imports should preserve both `source_snapshot_date` and `crawled_at` so that these differences can be reviewed instead of overwritten silently.

Recommended source tracking:

```text
department_requirement_sources
- id
- school
- department
- major
- source_url
- source_type        # html/pdf/hwp/image/manual
- curriculum_year
- crawled_at
- status             # collected/parsed/reviewed/applied
```

```text
requirement_parse_candidates
- id
- source_id
- parsed_json
- parser_type        # rule_based/llm/manual
- confidence
- status             # pending/approved/rejected
- reviewed_by
- reviewed_at
```

## RAG Direction

Included sources:

- Academic notices
- Academic policy guides
- Graduation requirement source documents
- Course guide documents
- Campus extracurricular programs
- Internal competitions, contests, lectures, mentoring, and capstone notices

Deferred sources:

- External competitions
- External activities
- Internships and hiring information
- Private certification and language test calendars

Recommended tables:

```text
rag_documents
- id
- school
- source_type
- source_table
- source_id
- title
- source_url
- content
- crawled_at
- updated_at
```

```text
rag_chunks
- id
- document_id
- chunk_index
- content
- embedding          # pgvector in implementation
- metadata           # JSONB
```

## LLM Direction

LLMs should:

- Explain graduation audit results.
- Explain why recommended courses matter.
- Help phrase roadmap guidance.
- Use RAG context for notices and campus opportunity answers.

LLMs should not:

- Decide whether graduation requirements are satisfied.
- Override deterministic requirement rules.
- Receive unnecessary personal identifiers such as student ID or raw transcript images.

## API Direction

Recommended MVP API groups:

```text
/api/v1/auth
/api/v1/users
/api/v1/academic-profile
/api/v1/curriculum
/api/v1/graduation
/api/v1/courses
/api/v1/recommendations
/api/v1/rag
/api/v1/ingestion
```

Implementation order:

1. DB schema and Alembic migrations
2. Seed data and CSV import format
3. Auth and academic profile APIs
4. Curriculum rule APIs
5. Graduation audit API
6. Course catalog and timetable APIs
7. Recommendation APIs
8. RAG APIs
9. Deployment automation

## Deployment Direction

Target stack:

- Frontend: Netlify
- Backend: FastAPI in Docker
- Backend host: AWS EC2
- Database: AWS RDS for PostgreSQL with pgvector
- Reverse proxy: Nginx
- CI/CD: GitHub Actions

Recommended infra folders:

```text
infra/
  docker/
  nginx/
  rds/
  github-actions/
```

Deployment concerns to decide before implementation:

- RDS connection string and secret management
- EC2 deployment user and SSH key handling
- Docker image build location: GitHub Actions or EC2
- Nginx TLS and backend upstream config
- CORS origins for Netlify preview and production domains
- Environment variable naming

## Open Decisions

- Which departments and curriculum years are supported in the first seed data set?
- What exact CSV format will be used for completed course records?
- Which pgvector embedding model will be used?
- Which LLM provider is used first: GPT, Claude, or both behind one interface?
- How much of overlap handling is included in the first graduation audit release?

## Current Recommendation

The agreed structure is appropriate for Plan-U because it preserves the product's most important boundary:

Graduation judgment is deterministic, while AI explains, searches, and recommends.

The repository should therefore move forward with this folder structure before implementation begins.

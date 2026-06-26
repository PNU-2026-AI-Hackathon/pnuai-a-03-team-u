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

The previous high-level folders were directionally correct, but two names were too broad:

- `ai` was too vague because Plan-U uses AI in several different ways: RAG search, LLM explanation, and recommendation support.
- `crawler` was too narrow because the data flow also includes CSV import, parsing, normalization, and later human-reviewed requirement ingestion.

The revised structure separates these concerns:

- `rag` handles retrieval over academic notices, graduation documents, course guides, campus opportunities, and competition notices.
- `llm` handles GPT or Claude calls for explanation and recommendation text.
- `recommendation` handles deterministic candidate generation and ranking inputs.
- `data_ingestion` handles CSV import, crawling, parsing, and normalization.
- `curriculum` owns graduation requirement rule data.
- `graduation_engine` owns graduation audit calculation.

This matches the agreed principle that AI must not decide graduation satisfaction. Deterministic backend logic performs graduation audits, while LLMs explain and prioritize based on validated results.

## Backend Structure

```text
backend/
  app/
    core/
    identity/
    academic_profile/
    curriculum/
    graduation_engine/
    course_catalog/
    recommendation/
    rag/
    llm/
    data_ingestion/
      csv_importers/
      crawlers/
      parsers/
      normalizers/
  migrations/
  scripts/
  seeds/
  tests/
```

### Module Responsibilities

`core`
- Settings, database session, security helpers, common exceptions, and shared dependencies.

`identity`
- Email and password authentication for MVP.
- JWT issuance and user identity APIs.
- Designed so Google, Kakao, and Naver OAuth can be added later through provider accounts.

`academic_profile`
- User academic programs: primary major, dual major, minor, interdisciplinary major.
- Completed course records.
- Certifications, language scores, competitions, and activities.
- CSV/manual course record input comes first. OCR can be added later.

`curriculum`
- Graduation requirement sets by school, department, major, program type, and curriculum year.
- Requirement categories, required courses, equivalency rules, prerequisite rules, and overlap rules.
- This module stores and manages rules; it does not calculate audits.

`graduation_engine`
- Calculates graduation audit results from user course records and curriculum rules.
- MVP calculates each selected program independently.
- Later versions can add integrated overlap handling across primary, dual, minor, and interdisciplinary programs.

`course_catalog`
- Courses, course offerings, sections, professors, capacity, and timetable blocks.
- MVP data can be imported from CSV.
- Later crawlers should upsert into the same normalized tables.

`recommendation`
- Candidate courses for the next semester.
- Timetable candidate generation.
- Deterministic filtering should happen here before LLM explanation.

`rag`
- Documents and chunks for academic information, graduation source documents, course guide documents, campus extracurricular opportunities, and internal competitions.
- Uses pgvector once embeddings are enabled.
- Used for search and chatbot context, not for final graduation judgment.

`llm`
- GPT/Claude client wrappers.
- Prompt templates for explaining audit results and recommendation reasons.
- Receives de-identified or minimal data.

`data_ingestion`
- `csv_importers`: MVP importers for course records and course offerings.
- `crawlers`: later crawlers for course catalog, academic notices, campus opportunities, and department requirement sources.
- `parsers`: text extraction or LLM-assisted parse candidates.
- `normalizers`: conversion into stable DB-ready records.

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
- What exact CSV format will be used for course offerings?
- What exact CSV format will be used for completed course records?
- Which pgvector embedding model will be used?
- Which LLM provider is used first: GPT, Claude, or both behind one interface?
- How much of overlap handling is included in the first graduation audit release?

## Current Recommendation

The agreed structure is appropriate for Plan-U because it preserves the product's most important boundary:

Graduation judgment is deterministic, while AI explains, searches, and recommends.

The repository should therefore move forward with this folder structure before implementation begins.

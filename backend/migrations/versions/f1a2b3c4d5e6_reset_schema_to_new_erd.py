"""reset schema to new ERD

기존 스키마(구 domains 구조 + 팀원 미머지 브랜치가 공유 DB에 직접 적용한
academic_programs/requirement_categories 등)를 전부 지우고, 새 ERD 기준
스키마로 다시 만든다. 팀 상의 후 실행할 것 — 기존 크롤링 데이터
(activities, user_activity_recommendations 제외 나머지)가 모두 사라진다.

2026-07-09 동결 수리: 원래 이 리비전은 upgrade()에서 "현재 시점"의 도메인
모델을 import해 Base.metadata.create_all()을 호출했다. 그 방식은 모델이
진화할수록 미래 리비전이 만들 테이블/컬럼을 미리 생성해 빈 DB에서
`alembic upgrade head` 전체 체인 재생이 깨진다(예: hierarchy 리비전
e6f7a8b9c0d1의 schools 생성과 충돌). 그래서 도입 당시(커밋 b8e7734) 모델이
만들던 DDL을 그대로 하드코딩해 동결했다. IF NOT EXISTS는 create_all의
checkfirst 의미론과 같다. 이미 이 리비전을 지난 DB(팀 Supabase)에는 영향이
없다.

이후 리비전이 add_column으로 추가하는 컬럼(users.advisor_consulted →
a2b3c4d5e6f7, users.major → b3c4d5e6f7a8, users/user_academic_programs의
college → c4d5e6f7a8b9)은 동결 DDL에 넣지 않았고, users.advisor_consulted는
이 리비전 이전(7a1f2c9d0b3e)에 이미 추가돼 있으므로 여기서 명시적으로
drop해 a2b3c4d5e6f7("post reset 보완")의 전제 상태를 복원한다.

Revision ID: f1a2b3c4d5e6
Revises: 3c9d5e1a7f24
Create Date: 2026-07-07 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '3c9d5e1a7f24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 지금까지 main/팀원 브랜치를 통틀어 존재했던 모든 구 테이블.
# activities / user_activity_recommendations는 실사용 중인 기능이라 제외(유지).
_OLD_TABLES = [
    "departments",
    "requirement_sets",
    "graduation_audits",
    "graduation_audit_program_results",
    "academic_programs",
    "academic_program_aliases",
    "department_academic_program_mappings",
    "requirement_categories",
    "requirement_courses",
    "requirement_text_rules",
    # 기존 이름 그대로 재생성되는 테이블도 컬럼 구조가 바뀌었으므로 drop 후 재생성
    "courses",
    "student_course_records",
    "user_academic_programs",
]

# 도입 당시(b8e7734) 도메인 모델 메타데이터가 생성하던 스키마의 동결본.
_FROZEN_DDL = [
    """
-- academic_info_articles
CREATE TABLE IF NOT EXISTS academic_info_articles (
	id SERIAL NOT NULL, 
	school VARCHAR(100), 
	category VARCHAR(100), 
	title VARCHAR(500) NOT NULL, 
	content TEXT, 
	source_url VARCHAR(500), 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)
    """,
    """
-- activities
CREATE TABLE IF NOT EXISTS activities (
	id SERIAL NOT NULL, 
	source VARCHAR(50) NOT NULL, 
	source_url VARCHAR(500) NOT NULL, 
	title VARCHAR(500) NOT NULL, 
	description TEXT, 
	author VARCHAR(100), 
	posted_date DATE, 
	deadline DATE, 
	category VARCHAR(100), 
	embedding VECTOR(1536), 
	is_pinned BOOLEAN NOT NULL, 
	views INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_activity_source_url UNIQUE (source, source_url)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_activities_category ON activities (category)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_activities_deadline ON activities (deadline)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_activities_embedding ON activities USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_activities_posted_date ON activities (posted_date)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_activities_source ON activities (source)
    """,
    """
-- courses
CREATE TABLE IF NOT EXISTS courses (
	id SERIAL NOT NULL, 
	school VARCHAR(100), 
	course_code VARCHAR(50), 
	course_name VARCHAR(255) NOT NULL, 
	department VARCHAR(200), 
	major VARCHAR(200), 
	category VARCHAR(50), 
	credits FLOAT, 
	year VARCHAR(10), 
	semester VARCHAR(20), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_courses_course_code ON courses (course_code)
    """,
    """
-- extracurricular_programs
CREATE TABLE IF NOT EXISTS extracurricular_programs (
	id SERIAL NOT NULL, 
	school VARCHAR(100), 
	title VARCHAR(500) NOT NULL, 
	category VARCHAR(100), 
	organizer VARCHAR(255), 
	apply_start_at TIMESTAMP WITHOUT TIME ZONE, 
	apply_end_at TIMESTAMP WITHOUT TIME ZONE, 
	program_start_at TIMESTAMP WITHOUT TIME ZONE, 
	program_end_at TIMESTAMP WITHOUT TIME ZONE, 
	target TEXT, 
	location VARCHAR(255), 
	url VARCHAR(500), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)
    """,
    """
-- graduation_requirements
CREATE TABLE IF NOT EXISTS graduation_requirements (
	id SERIAL NOT NULL, 
	school VARCHAR(100), 
	department VARCHAR(200), 
	major VARCHAR(200), 
	program_type VARCHAR(20), 
	curriculum_year VARCHAR(10), 
	required_total_credits INTEGER, 
	required_major_required INTEGER, 
	required_major_elective INTEGER, 
	required_general_required INTEGER, 
	required_general_elective INTEGER, 
	required_free_elective INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)
    """,
    """
-- users
CREATE TABLE IF NOT EXISTS users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	student_id VARCHAR(50), 
	school VARCHAR(100), 
	department VARCHAR(200), 
	career_goal VARCHAR(255), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)
    """,
    """
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)
    """,
    """
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_student_id ON users (student_id)
    """,
    """
-- course_offerings
CREATE TABLE IF NOT EXISTS course_offerings (
	id SERIAL NOT NULL, 
	course_id INTEGER NOT NULL, 
	school VARCHAR(100), 
	year VARCHAR(10), 
	semester VARCHAR(20), 
	section VARCHAR(20), 
	professor VARCHAR(100), 
	capacity INTEGER, 
	enrolled_count INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_course_offerings_course_id ON course_offerings (course_id)
    """,
    """
-- course_plans
CREATE TABLE IF NOT EXISTS course_plans (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	year VARCHAR(10), 
	semester VARCHAR(20), 
	status VARCHAR(20) NOT NULL, 
	total_credits FLOAT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_course_plans_user_id ON course_plans (user_id)
    """,
    """
-- course_roadmaps
CREATE TABLE IF NOT EXISTS course_roadmaps (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(255), 
	start_year VARCHAR(10), 
	target_graduation_year VARCHAR(10), 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_course_roadmaps_user_id ON course_roadmaps (user_id)
    """,
    """
-- portal_credentials
CREATE TABLE IF NOT EXISTS portal_credentials (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	portal VARCHAR(50) NOT NULL, 
	login_id VARCHAR(100) NOT NULL, 
	encrypted_password VARCHAR(500) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
    """,
    """
CREATE UNIQUE INDEX IF NOT EXISTS ix_portal_credentials_user_id ON portal_credentials (user_id)
    """,
    """
-- user_academic_programs
CREATE TABLE IF NOT EXISTS user_academic_programs (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	school VARCHAR(100), 
	department VARCHAR(200), 
	major VARCHAR(200), 
	program_type VARCHAR(20) NOT NULL, 
	curriculum_year VARCHAR(10), 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_user_academic_programs_user_id ON user_academic_programs (user_id)
    """,
    """
-- user_activity_recommendations
CREATE TABLE IF NOT EXISTS user_activity_recommendations (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	activity_id INTEGER NOT NULL, 
	similarity_score FLOAT, 
	career_weight FLOAT, 
	recency_weight FLOAT, 
	final_score FLOAT, 
	computed_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_activity_rec UNIQUE (user_id, activity_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(activity_id) REFERENCES activities (id) ON DELETE CASCADE
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_user_activity_recommendations_activity_id ON user_activity_recommendations (activity_id)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_user_activity_recommendations_final_score ON user_activity_recommendations (final_score)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_user_activity_recommendations_user_id ON user_activity_recommendations (user_id)
    """,
    """
-- user_certifications
CREATE TABLE IF NOT EXISTS user_certifications (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	expires_at DATE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_user_certifications_user_id ON user_certifications (user_id)
    """,
    """
-- user_competitions
CREATE TABLE IF NOT EXISTS user_competitions (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	category VARCHAR(100), 
	award VARCHAR(100), 
	held_at DATE, 
	description TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_user_competitions_user_id ON user_competitions (user_id)
    """,
    """
-- user_external_activities
CREATE TABLE IF NOT EXISTS user_external_activities (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	organization VARCHAR(255), 
	role VARCHAR(100), 
	start_date DATE, 
	end_date DATE, 
	description TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_user_external_activities_user_id ON user_external_activities (user_id)
    """,
    """
-- user_language_scores
CREATE TABLE IF NOT EXISTS user_language_scores (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	test_name VARCHAR(100) NOT NULL, 
	score VARCHAR(50) NOT NULL, 
	expires_at DATE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_user_language_scores_user_id ON user_language_scores (user_id)
    """,
    """
-- course_plan_items
CREATE TABLE IF NOT EXISTS course_plan_items (
	id SERIAL NOT NULL, 
	plan_id INTEGER NOT NULL, 
	offering_id INTEGER, 
	course_id INTEGER, 
	reason TEXT, 
	source VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(plan_id) REFERENCES course_plans (id), 
	FOREIGN KEY(offering_id) REFERENCES course_offerings (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_course_plan_items_plan_id ON course_plan_items (plan_id)
    """,
    """
-- course_roadmap_items
CREATE TABLE IF NOT EXISTS course_roadmap_items (
	id SERIAL NOT NULL, 
	roadmap_id INTEGER NOT NULL, 
	course_id INTEGER, 
	planned_grade INTEGER, 
	planned_year VARCHAR(10), 
	planned_semester VARCHAR(20), 
	reason TEXT, 
	source VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(roadmap_id) REFERENCES course_roadmaps (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_course_roadmap_items_roadmap_id ON course_roadmap_items (roadmap_id)
    """,
    """
-- course_times
CREATE TABLE IF NOT EXISTS course_times (
	id SERIAL NOT NULL, 
	offering_id INTEGER NOT NULL, 
	day_of_week VARCHAR(10), 
	start_time TIME WITHOUT TIME ZONE, 
	end_time TIME WITHOUT TIME ZONE, 
	classroom VARCHAR(100), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(offering_id) REFERENCES course_offerings (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_course_times_offering_id ON course_times (offering_id)
    """,
    """
-- student_course_records
CREATE TABLE IF NOT EXISTS student_course_records (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	course_id INTEGER, 
	user_academic_program_id INTEGER, 
	raw_course_code VARCHAR(50), 
	raw_course_name VARCHAR(255) NOT NULL, 
	category VARCHAR(50), 
	credits NUMERIC(4, 1), 
	year VARCHAR(10), 
	semester VARCHAR(20), 
	grade VARCHAR(10), 
	grade_point NUMERIC(3, 2), 
	is_retake BOOLEAN NOT NULL, 
	match_status VARCHAR(20) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id), 
	FOREIGN KEY(user_academic_program_id) REFERENCES user_academic_programs (id)
)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_student_course_records_user_academic_program_id ON student_course_records (user_academic_program_id)
    """,
    """
CREATE INDEX IF NOT EXISTS ix_student_course_records_user_id ON student_course_records (user_id)
    """
]


def upgrade() -> None:
    """Upgrade schema."""
    for table in _OLD_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')

    # a2b3c4d5e6f7(add advisor_consulted post reset)의 전제 복원 — 위 동결 docstring 참고.
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS advisor_consulted")

    for stmt in _FROZEN_DDL:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("전면 리셋 마이그레이션은 downgrade를 지원하지 않습니다.")

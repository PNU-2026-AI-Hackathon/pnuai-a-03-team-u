import datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    student_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    # 학부제로 다전공(복수전공/부전공)까지 나뉘는 경우의 세부 전공.
    # "OO과"처럼 학과 자체가 곧 전공이라 세부 전공 구분이 없으면 null.
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    academic_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "freshman"(신입학) | "transfer"(편입학). 편입생은 1·2학년 커리큘럼을 밟지 않아
    # 로드맵을 "입학 전 인정 학점 + 3·4학년"으로 구성해야 한다.
    #
    # 이 값이 생기기 전에는 StudentCourseRecord에 semester="입학전성적" 행이 있는지
    # 보고 편입 여부를 추론했다. 포털 동기화를 아직 안 한 편입생은 추론이 불가능했고,
    # 반대로 조기이수 인정 학점이 있는 신입생을 편입생으로 잘못 볼 수도 있었다.
    #
    # nullable + server_default를 함께 둔다: 이미 가입한 사용자의 행을 한 번에
    # 채워야 하고, 값이 없는 옛 행도 그대로 읽혀야 한다.
    admission_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, server_default="freshman", default="freshman"
    )
    career_goal: Mapped[str | None] = mapped_column(String(255))
    advisor_consulted: Mapped[bool] = mapped_column(default=False)
    # One-Stop 포털 학적부(fetch_student_record)의 "지도교수" 필드에서 크롤링.
    # 없으면 아직 동기화 전이거나 지도교수가 아직 배정되지 않은 것.
    advisor_name: Mapped[str | None] = mapped_column(String(100))
    # 학과 공통 졸업요건 원본은 건드리지 않고, 사용자가 직접 보정한 표시값만 보관한다.
    graduation_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 보존기간 정책(security-privacy-plan.md P2)의 '미접속' 판단 근거.
    # updated_at은 프로필 수정에만 반응하고 로그인(조회)에는 안 움직여서 못 쓴다.
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    # 개인정보 수집·이용 및 LLM/Langfuse 처리위탁 동의(회원가입 시 필수 체크박스).
    # nullable + server_default="false": 이미 가입한 옛 사용자 행은 동의를 받은 적이
    # 없으므로 false로 채워지고(허위로 true를 만들지 않는다), 그 사실을
    # privacy_consent_at(None)로도 함께 드러낸다. 재동의 UI는 이번 범위 밖.
    privacy_consent: Mapped[bool] = mapped_column(default=False, server_default="false")
    privacy_consent_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)


class PasswordResetToken(TimestampMixin, Base):
    """비밀번호 재설정 링크의 1회용 토큰.

    본인확인은 부산대 웹메일 수신으로만 한다(7/3 회의 주제 4와 연결). 시안의
    "학번 + 이름" 확인은 둘 다 사실상 공개 정보라 남의 계정을 바꿀 수 있어 쓰지 않는다.

    토큰 원문은 저장하지 않고 sha256 해시만 둔다. DB가 유출돼도 그 값만으로는
    재설정 링크를 만들 수 없다.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    # 한 번 쓰면 채워지고, 이후 같은 토큰은 거부된다.
    used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PortalCredential(TimestampMixin, Base):
    """학교 포털(One-Stop 등) 자동 크롤링을 위한 계정정보.

    비밀번호는 평문 저장하지 않고 app.core.security.encrypt_secret()으로
    암호화한 값만 저장한다.
    """

    __tablename__ = "portal_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    portal: Mapped[str] = mapped_column(String(50), default="pnu_onestop")
    login_id: Mapped[str] = mapped_column(String(100))
    encrypted_password: Mapped[str] = mapped_column(String(500))


class UserActivity(TimestampMixin, Base):
    """비교과 활동. 동아리/인턴/봉사 같은 외부활동과 공모전/수상을 하나로 합친 테이블.

    "내 정보" 페이지의 비교과 활동 리스트가 이 둘을 구분 없이 하나의 목록으로
    보여줘서(기관명/설명/링크만 있으면 됨) 굳이 두 테이블로 나눌 이유가 없었다.
    """

    __tablename__ = "user_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    organization: Mapped[str | None] = mapped_column(String(255))
    # 자유 텍스트 분류(예: "동아리", "공모전", "인턴", "프로젝트"). 정해진 값 집합 없음.
    category: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str | None] = mapped_column(String(100))
    award: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)


class UserCertification(TimestampMixin, Base):
    """자격증 보유 이력."""

    __tablename__ = "user_certifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime.date | None] = mapped_column(Date)


class UserLanguageScore(TimestampMixin, Base):
    """어학 성적 보유 이력."""

    __tablename__ = "user_language_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    test_name: Mapped[str] = mapped_column(String(100))
    score: Mapped[str] = mapped_column(String(50))
    expires_at: Mapped[datetime.date | None] = mapped_column(Date)

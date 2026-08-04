"""SMTP 설정 점검 · 테스트 메일 발송.

.env의 SMTP_* 값이 제대로 물리는지, 실제로 메일이 나가는지 확인한다.
비밀번호는 .env에서 읽기만 하고 화면에 출력하지 않는다.

    # 설정만 점검(발송 안 함)
    python -m scripts.check_smtp

    # 지정한 주소로 테스트 메일 1통 발송
    python -m scripts.check_smtp --to 아이디@pusan.ac.kr
"""

from __future__ import annotations

import argparse
import logging
import smtplib

from app.core.config import settings
from app.core.mailer import is_smtp_configured, send_password_reset_email


def _mask(value: str | None) -> str:
    if not value:
        return "(비어 있음)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def show_settings() -> None:
    print("[설정]")
    print(f"  SMTP_HOST       : {settings.SMTP_HOST or '(비어 있음)'}")
    print(f"  SMTP_PORT       : {settings.SMTP_PORT}")
    print(f"  SMTP_USER       : {settings.SMTP_USER or '(비어 있음)'}")
    print(f"  SMTP_PASSWORD   : {_mask(settings.SMTP_PASSWORD)}")
    print(f"  SMTP_USE_TLS    : {settings.SMTP_USE_TLS}")
    print(f"  SMTP_FROM       : {settings.SMTP_FROM}")
    print(f"  링크 주소       : {settings.PASSWORD_RESET_URL_BASE}")
    print(f"  링크 유효시간   : {settings.PASSWORD_RESET_TOKEN_TTL_MINUTES}분")


def check_connection() -> bool:
    """접속과 로그인까지만 확인한다(메일은 보내지 않음)."""
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    except smtplib.SMTPAuthenticationError:
        print("\n[실패] 인증 거부.")
        print("       Resend면 SMTP_USER 가 'resend'(고정)인지, SMTP_PASSWORD 가")
        print("       API 키(re_ 로 시작)인지 확인하세요. 계정 비밀번호가 아닙니다.")
        return False
    except Exception as error:  # noqa: BLE001 - 원인을 그대로 보여주는 게 목적
        print(f"\n[실패] 접속 실패: {type(error).__name__}: {error}")
        return False

    print("\n[성공] 접속·로그인 확인")
    return True


def _explain_send_failure() -> None:
    """발송 단계에서 자주 걸리는 Resend 제약을 안내한다."""
    print("       자주 걸리는 원인:")
    print("       · 도메인 인증 전에는 SMTP_FROM 이 onboarding@resend.dev 여야 합니다.")
    print("       · 샌드박스 상태에서는 Resend 가입에 쓴 본인 주소로만 보낼 수 있습니다.")
    print("         (다른 주소로 보내려면 Resend 에서 도메인 인증이 필요합니다)")


def main() -> None:
    parser = argparse.ArgumentParser(description="SMTP 설정 점검")
    parser.add_argument("--to", help="테스트 메일을 받을 주소. 없으면 발송하지 않고 점검만 한다")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    show_settings()

    if not is_smtp_configured():
        print("\n[안내] SMTP_HOST가 비어 있어 메일을 보내지 않습니다.")
        print("       비밀번호 재설정 링크는 서버 로그에만 남습니다(로컬 개발용 동작).")
        return

    if not check_connection():
        raise SystemExit(1)

    if not args.to:
        print("\n실제 발송까지 확인하려면 --to 주소를 붙여 다시 실행하세요.")
        return

    print(f"\n{args.to} 로 테스트 메일을 보냅니다...")
    sent = send_password_reset_email(
        to=args.to,
        reset_url=f"{settings.PASSWORD_RESET_URL_BASE}?token=TEST-TOKEN-발송확인용",
        ttl_minutes=settings.PASSWORD_RESET_TOKEN_TTL_MINUTES,
    )
    if sent:
        print("[성공] 발송했습니다. 받은편지함(및 스팸함)을 확인하세요.")
        print("       메일 안의 링크는 테스트용 가짜 토큰이라 실제로는 동작하지 않습니다.")
    else:
        print("[실패] 발송하지 못했습니다. 위 로그를 확인하세요.")
        _explain_send_failure()
        raise SystemExit(1)


if __name__ == "__main__":
    main()

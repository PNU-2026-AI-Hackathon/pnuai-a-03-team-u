"""메일 발송.

SMTP_HOST가 설정돼 있으면 실제로 보내고, 없으면 본문을 로그로만 남긴다.
로컬에서 메일 서버 없이 비밀번호 재설정 흐름을 끝까지 확인하기 위한 것이다.
운영에서는 SMTP_* 를 채워야 하고, 비어 있으면 기동 로그에 경고가 남는다.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_smtp_configured() -> bool:
    return bool(settings.SMTP_HOST)


def send_email(to: str, subject: str, body: str) -> bool:
    """메일을 보낸다. 실제로 발송했으면 True, 로그로만 남겼으면 False.

    호출부가 성공/실패로 분기하지 않도록 예외를 밖으로 내보내지 않는다.
    비밀번호 재설정은 메일 발송 실패 여부를 응답에 드러내면 안 되기 때문이다
    (가입 여부가 노출된다).
    """
    if not is_smtp_configured():
        logger.warning(
            "SMTP가 설정되지 않아 메일을 보내지 않았습니다. 아래 내용을 직접 확인하세요.\n"
            "--- to: %s / subject: %s ---\n%s\n--- end ---",
            to,
            subject,
            body,
        )
        return False

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(message)
    except Exception:
        # 수신자 주소는 남기되 본문(토큰 포함)은 로그에 남기지 않는다.
        logger.exception("비밀번호 재설정 메일 발송 실패: to=%s", to)
        return False

    return True


def send_password_reset_email(to: str, reset_url: str, ttl_minutes: int) -> bool:
    subject = "[Plan U] 비밀번호 재설정 안내"
    body = (
        "Plan U 비밀번호 재설정 요청이 접수되었습니다.\n\n"
        f"아래 주소에서 새 비밀번호를 설정해 주세요. (유효시간 {ttl_minutes}분)\n"
        f"{reset_url}\n\n"
        "본인이 요청하지 않았다면 이 메일을 무시하셔도 됩니다. "
        "링크를 사용하지 않으면 비밀번호는 그대로 유지됩니다.\n"
    )
    return send_email(to, subject, body)

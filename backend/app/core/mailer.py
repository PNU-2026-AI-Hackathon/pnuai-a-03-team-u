"""메일 발송.

SMTP_HOST가 설정돼 있으면 실제로 보내고, 없으면 본문을 로그로만 남긴다(개발 환경에서만).
로컬에서 메일 서버 없이 비밀번호 재설정 흐름을 끝까지 확인하기 위한 것이다.
운영에서는 SMTP_* 를 채워야 하고, 비어 있으면 기동 로그에 경고가 남는다
(`startup_log()` — `app/main.py`의 lifespan에서 부른다).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import NamedTuple

from app.core.config import is_dev_environment, settings

logger = logging.getLogger(__name__)


# Resend SMTP 릴레이 기본값. `RESEND_API`만 채웠을 때 쓰는 값이다.
# https://resend.com/docs/send-with-smtp
_RESEND_HOST = "smtp.resend.com"
_RESEND_PORT = 587
_RESEND_USER = "resend"  # Resend는 사용자명이 고정이고 비밀번호 자리에 API 키를 넣는다


class SmtpSettings(NamedTuple):
    host: str | None
    port: int
    user: str | None
    password: str | None
    use_tls: bool


def resolve_smtp() -> SmtpSettings:
    """실제로 접속에 쓸 SMTP 값. `SMTP_*`가 우선, 없으면 `RESEND_API`로 채운다.

    키를 두 벌(RESEND_API와 SMTP_PASSWORD) 적게 하지 않으려는 것이다. `.env`에
    `RESEND_API=re_...` 한 줄만 있어도 발송이 되고, 다른 메일 서버를 쓰는 사람은
    기존대로 `SMTP_*`를 직접 채우면 그쪽이 이긴다.
    """
    if settings.SMTP_HOST:
        return SmtpSettings(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            user=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_USE_TLS,
        )
    if settings.RESEND_API:
        return SmtpSettings(
            host=_RESEND_HOST,
            port=_RESEND_PORT,
            user=settings.SMTP_USER or _RESEND_USER,
            password=settings.SMTP_PASSWORD or settings.RESEND_API,
            use_tls=True,
        )
    return SmtpSettings(host=None, port=settings.SMTP_PORT, user=None, password=None,
                        use_tls=settings.SMTP_USE_TLS)


def is_smtp_configured() -> bool:
    return bool(resolve_smtp().host)


def startup_log() -> None:
    """기동 시 메일 설정 상태를 한 줄 남긴다.

    예전에는 이 모듈 docstring이 "비어 있으면 기동 로그에 경고가 남는다"고 적어놓고
    실제로는 아무 데서도 부르지 않았다 — 배포에서 SMTP를 빠뜨려도 조용했고,
    "비밀번호 재설정 메일이 안 온다"는 문의를 받고 나서야 알 수 있었다.
    """
    # 메일이 나가도 링크가 localhost면 아무 데도 안 간다. 받는 사람 PC의 localhost라
    # 배포에서는 **무조건** 깨진다 — 그런데 메일은 정상 발송되므로 아무도 눈치채지
    # 못한다. `PASSWORD_RESET_URL_BASE`를 배포 프론트 주소로 덮어써야 한다.
    base = settings.PASSWORD_RESET_URL_BASE or ""
    if not is_dev_environment() and ("localhost" in base or "127.0.0.1" in base):
        logger.error(
            "PASSWORD_RESET_URL_BASE가 아직 로컬 주소입니다 (%s). 배포에서는 메일 링크가 "
            "받는 사람 PC의 localhost를 가리켜 열리지 않습니다 — 프론트 배포 주소로 "
            "바꾸세요 (예: https://planu-pnu.netlify.app/reset-password).",
            base,
        )

    smtp = resolve_smtp()
    if smtp.host:
        source = "RESEND_API" if not settings.SMTP_HOST else "SMTP_HOST"
        logger.info(
            "메일 발송 설정됨 (host=%s, from=%s, 출처=%s)", smtp.host, settings.SMTP_FROM, source
        )
        if not (smtp.user and smtp.password):
            logger.warning(
                "SMTP 호스트는 있는데 사용자/비밀번호가 비어 있습니다 — 인증이 필요한 "
                "서버(Resend 등)라면 발송이 실패합니다. 인증 없이 쓰는 릴레이면 무시하세요."
            )
    elif is_dev_environment():
        logger.warning(
            "SMTP 미설정 — 비밀번호 재설정 메일을 보내지 않고 링크를 이 로그에 남깁니다 "
            "(ENV=%s). 실제 발송은 .env에 RESEND_API=re_... 한 줄을 넣으면 됩니다.",
            settings.ENV,
        )
    else:
        logger.error(
            "SMTP 미설정 상태로 기동했습니다 (ENV=%s). 비밀번호 재설정 메일이 나가지 않고, "
            "링크는 보안상 로그에도 남기지 않습니다 — 사용자는 비밀번호를 되찾을 수 없습니다.",
            settings.ENV,
        )


def send_email(to: str, subject: str, body: str) -> bool:
    """메일을 보낸다. 실제로 발송했으면 True, 로그로만 남겼으면 False.

    호출부가 성공/실패로 분기하지 않도록 예외를 밖으로 내보내지 않는다.
    비밀번호 재설정은 메일 발송 실패 여부를 응답에 드러내면 안 되기 때문이다
    (가입 여부가 노출된다).
    """
    if not is_smtp_configured():
        # 본문에는 비밀번호 재설정 링크(=계정 탈취에 바로 쓰이는 자격증명)가 들어 있다.
        # 로컬 개발에서 메일 서버 없이 흐름을 확인하려고 로그로 출력하는데, 배포에서
        # SMTP_HOST가 비어 있으면 로그 접근자가 임의 계정을 가져갈 수 있다.
        # 그래서 개발 환경이 아니면 링크를 찍지 않는다 (security-privacy-plan.md P0-4).
        # 판단 기준은 크롤러 폴백 가드(P1-4)와 반드시 같아야 한다 — 예전에는 여기만
        # `ENV == "local"` 정확 일치라 `ENV=dev` 개발자는 폴백은 열리는데 링크는
        # 안 찍혔다. 그래서 `is_dev_environment()` 하나로 통일했다.
        if is_dev_environment():
            logger.warning(
                "SMTP가 설정되지 않아 메일을 보내지 않았습니다. 아래 내용을 직접 확인하세요.\n"
                "--- to: %s / subject: %s ---\n%s\n--- end ---",
                to,
                subject,
                body,
            )
        else:
            logger.error(
                "SMTP 미설정 상태에서 메일 발송이 시도됐습니다 (ENV=%s, to=%s, subject=%s). "
                "본문은 재설정 링크를 포함하므로 로그에 남기지 않습니다 — SMTP_HOST를 설정하세요.",
                settings.ENV, to, subject,
            )
        return False

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    smtp = resolve_smtp()
    try:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=10) as server:
            if smtp.use_tls:
                server.starttls()
            if smtp.user and smtp.password:
                server.login(smtp.user, smtp.password)
            server.send_message(message)
    except Exception:
        # 수신자 주소는 남기되 본문(토큰 포함)은 로그에 남기지 않는다.
        logger.exception("비밀번호 재설정 메일 발송 실패: to=%s", to)
        # **반쪽 설정 함정**: SMTP_HOST만 있고 SMTP_PASSWORD가 비어 있으면
        # `is_smtp_configured()`가 True라 위 미설정 폴백을 건너뛰는데, 실제 발송은
        # 인증 실패로 죽는다. 그러면 메일도 안 오고 로그에 링크도 없어서 개발자는
        # 비밀번호 재설정 흐름을 **아예 확인할 수 없다** — 설정을 안 한 것보다 나쁘다.
        # `.env.example`을 그대로 복사하면 정확히 이 상태가 됐다(2026-08-20 실측).
        # 개발 환경에서만 링크를 흘린다 — 판단 기준은 위 미설정 폴백과 동일해야 한다.
        if is_dev_environment():
            logger.warning(
                "발송에 실패해 메일이 가지 않았습니다. 아래 내용을 직접 확인하세요.\n"
                "--- to: %s / subject: %s ---\n%s\n--- end ---",
                to,
                subject,
                body,
            )
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

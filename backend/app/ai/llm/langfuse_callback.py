"""Langfuse 트레이싱 통합. 두 에이전트(`roadmap_chat`, `timetable_chat`)에서
`observe_agent_call(...)` 컨텍스트 매니저로 각 요청을 감싼다.

Langfuse v4는 OpenTelemetry 기반이라 전역 client 하나를 초기화하고,
`langchain.CallbackHandler`는 그 client를 참조한다. 이 모듈은:

- 콜백 하나짜리 `config` (langchain `.invoke(config=...)` 용)
- root observation을 `as_type="agent"`로 명시 → Langfuse UI Agent Graph에 표시됨
- 트레이스 뿌리에 사용자 메시지만 input으로 넣고 최종 응답을 output으로 → UI 가독성
- session_id/user_id/tags를 `propagate_attributes`로 자식 span 전부에 자동 전파
- shutdown 시 pending trace flush (main.py lifespan에서 부름)

키 3개(PUBLIC/SECRET/BASE_URL) 중 하나라도 비면 client가 만들어지지 않고
컨텍스트 매니저는 no-op으로 동작한다 (config는 빈 dict).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from functools import lru_cache
from typing import Any, Iterator

from app.core.config import settings

from .langfuse_masking import mask_data

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> Any | None:
    """전역 Langfuse client. 키 미설정 시 None. 프로세스당 한 번만 초기화."""
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        return None

    if not settings.LANGFUSE_USER_ID_SALT:
        logger.warning(
            "LANGFUSE_USER_ID_SALT가 비어 있습니다. user_id 해시가 salt=''로 만들어져 "
            "rainbow 공격에 취약합니다. .env에 아무 문자열이나 채우세요."
        )

    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_BASE_URL,
        environment=settings.ENV,
        mask=mask_data,
    )


@lru_cache(maxsize=1)
def _get_handler() -> Any | None:
    """CallbackHandler 싱글턴. client 없으면 None."""
    if _get_client() is None:
        return None
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        return None
    return CallbackHandler()


def hash_user_id(user_id: int | None) -> str | None:
    """user_id 해시(12자 hex). salt 없으면 salt=""로 폴백."""
    if user_id is None:
        return None
    salt = settings.LANGFUSE_USER_ID_SALT or ""
    digest = hashlib.sha256(f"{salt}:{user_id}".encode("utf-8")).hexdigest()
    return digest[:12]


class _AgentTrace:
    """observe_agent_call 컨텍스트가 yield 하는 객체.

    - `.config`: langchain `.invoke(config=...)`에 넘긴다.
    - `.set_output(x)`: root observation의 output을 세팅한다.
    - `.add_metadata(dict)`: root observation metadata에 병합. 필터·breakdown용.
    - `.score(name, value)`: 대시보드에서 시계열/분포 차트로 잡히는 정량 점수.
      value는 float(0~1 권장) 또는 문자열(카테고리) 둘 다 가능.

    모두 Langfuse 꺼진 상태(root_span=None)에선 no-op.
    """

    def __init__(self, config: dict[str, Any], root_span: Any | None):
        self.config = config
        self._root = root_span

    def set_output(self, output: Any) -> None:
        if self._root is None:
            return
        try:
            self._root.update(output=output)
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse root observation output 세팅 실패")

    def add_metadata(self, metadata: dict[str, Any]) -> None:
        if self._root is None or not metadata:
            return
        try:
            self._root.update(metadata=metadata)
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse metadata 병합 실패")

    def score(
        self,
        name: str,
        value: float | int | str | bool,
        *,
        comment: str | None = None,
    ) -> None:
        if self._root is None:
            return
        try:
            # bool을 float로 정규화(True=1.0, False=0.0) — Langfuse UI에서 평균 집계 가능.
            if isinstance(value, bool):
                value = 1.0 if value else 0.0
            self._root.score_trace(name=name, value=value, comment=comment)
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse trace 스코어 세팅 실패 (%s)", name)

    @contextlib.contextmanager
    def span(self, name: str, *, as_type: str = "span", input: Any = None) -> Iterator[Any]:
        """root 안에 자식 span을 만든다. UI 트레이스 트리에서 페이즈별 시간이 보인다.

        as_type: "span" | "retriever" | "tool" | "chain" — Langfuse observation type.
        Langfuse 꺼진 상태면 no-op context.
        """
        if self._root is None:
            yield None
            return
        try:
            with self._root.start_as_current_observation(
                as_type=as_type, name=name, input=input
            ) as child:
                yield child
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse child span 생성 실패 (%s)", name)
            yield None


@contextlib.contextmanager
def observe_agent_call(
    *,
    agent: str,
    user_id: int | None,
    session_id: int | str | None,
    user_message: str,
    extra_metadata: dict[str, Any] | None = None,
) -> Iterator[_AgentTrace]:
    """에이전트 한 실행 전체를 하나의 root observation으로 감싼다.

    yield 하는 `_AgentTrace.config`를 langchain의 `.invoke(config=...)`에 넘기면
    LLM 호출 · 툴 호출 · 재시도가 전부 이 root observation의 자식 span으로 붙는다.
    root의 input은 사용자 원문 메시지, output은 최종 응답 텍스트로 세팅해 UI
    가독성을 확보한다(전체 messages 배열은 자식 LLM span에서 볼 수 있다).
    """
    client = _get_client()
    handler = _get_handler()
    if client is None or handler is None:
        # Langfuse 꺼진 상태 — 완전한 no-op.
        yield _AgentTrace(config={}, root_span=None)
        return

    from langfuse import propagate_attributes  # lazy import

    input_data = {"message": user_message}
    if extra_metadata:
        input_data.update(extra_metadata)

    with client.start_as_current_observation(
        as_type="agent",
        name=agent,
        input=input_data,
    ) as root_span:
        with propagate_attributes(
            session_id=str(session_id) if session_id is not None else None,
            user_id=hash_user_id(user_id),
            tags=[agent, settings.ENV],
            trace_name=agent,
        ):
            yield _AgentTrace(
                config={"callbacks": [handler]},
                root_span=root_span,
            )


def flush() -> None:
    """FastAPI shutdown 훅에서 부른다. 아직 안 보낸 trace를 배출."""
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:  # noqa: BLE001
        logger.exception("Langfuse flush 실패")


def startup_log() -> None:
    """FastAPI startup에서 부른다. langfuse 상태를 로그로 남긴다."""
    if _get_client() is None:
        logger.info("Langfuse 트레이싱 비활성 (LANGFUSE_* 키 미설정).")
    else:
        logger.info(
            "Langfuse 트레이싱 활성 (host=%s, environment=%s).",
            settings.LANGFUSE_BASE_URL,
            settings.ENV,
        )

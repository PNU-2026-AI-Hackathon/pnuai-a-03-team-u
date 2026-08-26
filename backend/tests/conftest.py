"""테스트 공통 설정.

## 레이트 리밋은 기본 비활성

이 레포의 API 테스트 상당수는 FastAPI를 거치지 않고 **엔드포인트 함수를 직접 호출**한다
(예: `request_password_reset(PasswordResetRequest(...), db)`). slowapi의 `@limiter.limit`
데코레이터는 첫 인자가 `starlette.requests.Request`이길 요구해서, 켜둔 채로는 그런 호출이
전부 예외로 죽는다 — 레이트 리밋과 무관한 테스트가 리밋 때문에 깨지는 셈이다.

또 하나: 리밋 카운터는 프로세스 전역이라 켜둔 채 테스트를 돌리면 **테스트 간 간섭**이
생긴다. 로그인 테스트 여러 개가 순서대로 돌면 뒤쪽이 429를 받는 식이다.

리밋 동작 자체는 `test_rate_limit.py`가 TestClient로 실제 HTTP 경로를 태워서 검증한다.
"""

import pytest

from app.ai.llm import langfuse_callback
from app.core.config import settings
from app.core.ratelimit import limiter


@pytest.fixture(autouse=True, scope="session")
def _disable_langfuse_tracing():
    """테스트가 팀 공유 Langfuse(langfuse-planu.xyz)에 가짜 trace를 남기지 않게 한다.

    `run_roadmap_chat`/`run_timetable_chat`을 실제로 호출하는 테스트(예:
    FinishGateBehaviourTest)는 LLM 클라이언트(`_build_llm`)만 스크립트로 바꿔치기하고
    `observe_agent_call`은 그대로 살아있다 — .env의 LANGFUSE_* 키가 남아있으면 테스트용
    스크립트 응답("예산 소진" 같은 리터럴 문자열)이 그대로 실제 trace로 팀 Langfuse에
    올라간다(2026-08-26 실측: 로컬 pytest 전체 스위트 실행이 그대로 찍혀서, 사용자가
    실제 API 예산 소진으로 오인함). client/handler는 `lru_cache`라 세션 시작 시 한 번만
    비워두면 된다 — 개별 테스트가 이미 만들어진 캐시를 다시 채울 일이 없다.
    """
    settings.LANGFUSE_PUBLIC_KEY = None
    settings.LANGFUSE_SECRET_KEY = None
    langfuse_callback._get_client.cache_clear()
    langfuse_callback._get_handler.cache_clear()
    yield


@pytest.fixture(autouse=True)
def _disable_rate_limit_by_default(request):
    """리밋을 끈 상태로 테스트를 돌린다.

    `@pytest.mark.ratelimit`을 붙인 테스트에서만 켠다.
    """
    wants_limit = request.node.get_closest_marker("ratelimit") is not None
    previous = limiter.enabled
    limiter.enabled = wants_limit
    if wants_limit:
        limiter.reset()
    try:
        yield
    finally:
        limiter.enabled = previous


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "ratelimit: 이 테스트에서만 레이트 리밋을 켠다 (기본은 비활성)"
    )

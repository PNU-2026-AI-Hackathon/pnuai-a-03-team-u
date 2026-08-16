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

from app.core.ratelimit import limiter


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

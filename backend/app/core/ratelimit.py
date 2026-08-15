"""엔드포인트별 레이트 리밋.

`docs/backend/security-privacy-plan.md` P0-1. 막으려는 것 세 가지:

1. **로그인 brute force** — `/auth/login`이 무제한이었다.
2. **재설정 메일 폭탄** — `/auth/password-reset/request`가 무제한이라 남의 메일함을
   채우고 토큰을 남발할 수 있었다.
3. **챗 LLM 비용 폭탄** — 로그인만 하면 한 사용자가 초당 수십 번 챗을 호출할 수 있었다.
   골든 스윕 실측으로 한 대화가 입력 6만 토큰을 쓰기도 한다. 이게 제일 급했다.

## 키 선택

- 인증 전 엔드포인트(로그인·재설정)는 **IP**로 센다.
- 인증 후 엔드포인트(챗·포털동기화)는 **user_id**로 센다. IP로 세면 같은 학교
  네트워크·NAT 뒤의 학생들이 서로의 몫을 잡아먹는다.

## 저장소

기본은 in-memory다. 워커가 여러 개면 프로세스마다 따로 세므로 실효 한도가 워커 수만큼
느슨해진다. `RATE_LIMIT_STORAGE_URI`(예: redis://...)를 주면 공유 저장소를 쓴다.
지금 배포는 단일 인스턴스라 기본값으로 충분하고, 스케일아웃 시점에 채우면 된다.

끄는 방법: `RATE_LIMIT_ENABLED=false` (로컬에서 반복 테스트할 때).
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _user_or_ip(request: Request) -> str:
    """인증된 요청은 user_id로, 아니면 IP로 센다.

    `get_current_user` 의존성이 이미 돌아 `request.state.user_id`를 채워둔 경우에만
    user_id를 쓴다 — 여기서 토큰을 다시 디코드하면 리밋 계산이 인증 로직과 어긋난다.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=_user_or_ip,
    storage_uri=settings.RATE_LIMIT_STORAGE_URI or None,
    enabled=settings.RATE_LIMIT_ENABLED,
    # ⚠️ headers_enabled는 반드시 False로 둔다. True로 켜면 **성공 응답이 전부 500이 된다.**
    #
    # slowapi 0.1.10 `extension.py`의 sync/async wrapper는 엔드포인트 반환값이
    # starlette Response가 아니면 `_inject_headers(kwargs.get("response"), ...)`를 부르고,
    # `_inject_headers`는 `headers_enabled`가 켜져 있을 때 response가 Response가 아니면
    # 예외를 던진다. 우리 엔드포인트는 전부 Pydantic 모델을 반환하고 `response: Response`
    # 파라미터를 선언하지 않으므로 kwargs["response"]가 없다 → None → 예외 → 500.
    #
    # 즉 리밋이 걸린 /auth/login, /auth/signup, /auth/password-reset/request,
    # /me/portal-sync, /rag/ingest, 로드맵 /chat, 시간표 /recommend 가 **정상 요청에서**
    # 죽는다. 429 경로와 401 경로는 헤더 주입 전에 빠져나가서 멀쩡해 보이는 게 함정이다.
    #
    # 남은 횟수 헤더가 정말 필요해지면, 켜는 것만으로는 안 되고 리밋이 걸린 **모든**
    # 엔드포인트 시그니처에 `response: Response`를 추가해야 한다. 하나라도 빠뜨리면 그
    # 엔드포인트만 조용히 500이 되므로, 그때는 회귀 테스트도 엔드포인트별로 깔아야 한다.
    # 지금 프론트는 이 헤더를 읽지 않으므로 끄는 쪽이 이득이다.
    headers_enabled=False,
)


# 정책. 값은 settings로 빼서 배포 환경별로 조정 가능하게 한다.
#
# 챗이 가장 빡빡한 이유: 비용이 요청당 수 센트씩 나가고, 정상 사용자는 분당 몇 번을
# 넘길 이유가 없다. 일 한도까지 두는 건 분당 한도만으로는 하루치 총액을 못 막기 때문이다.
LOGIN_LIMIT = settings.RATE_LIMIT_LOGIN
PASSWORD_RESET_LIMIT = settings.RATE_LIMIT_PASSWORD_RESET
SIGNUP_LIMIT = settings.RATE_LIMIT_SIGNUP
CHAT_LIMITS = settings.RATE_LIMIT_CHAT       # "10/minute;100/day" 처럼 세미콜론 구분
PORTAL_SYNC_LIMIT = settings.RATE_LIMIT_PORTAL_SYNC
RAG_INGEST_LIMIT = settings.RATE_LIMIT_RAG_INGEST

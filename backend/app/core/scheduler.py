"""APScheduler 인스턴스.

FastAPI lifespan에서 start/shutdown을 호출한다. 추천활동(비교과 크롤링 +
임베딩 + 추천) 기능은 다시 설계해서 구현할 예정이라 지금은 등록된 잡이 없다.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Seoul")

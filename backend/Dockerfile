FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Python 패키지를 먼저 설치해 애플리케이션 코드 변경 시 의존성 레이어를 재사용한다.
# Playwright Python 패키지만으로는 Railway에서 Chromium을 실행할 수 없으므로
# 브라우저 바이너리와 Linux 시스템 라이브러리도 이미지에 함께 포함한다.
COPY requirements.txt constraints.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt -c constraints.txt \
    && playwright install --with-deps chromium

COPY . .

CMD ["/bin/sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

"""APScheduler 인스턴스 및 반복 작업 등록.

FastAPI lifespan에서 start/shutdown을 호출한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Seoul")


def _crawl_notice_boards() -> None:
    from app.core.db import SessionLocal
    from app.ingestion.crawlers.notice_board_crawler import crawl_all_notice_boards
    from app.ingestion.normalizers.activity_normalizer import (
        remove_stale_activities,
        upsert_all_activities,
    )
    from app.ingestion.normalizers.dedup_activities import remove_duplicate_activities

    logger.info("notice board crawl started")
    rows = crawl_all_notice_boards()

    # raw JSON 백업
    output_dir = Path("raw_data/crawled_data/notice_boards")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{date.today().isoformat()}.json"
    output_path.write_text(
        json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # DB upsert
    db = SessionLocal()
    try:
        saved = upsert_all_activities(db, rows)
        logger.info("notice board crawl done: total=%d saved=%d", len(rows), len(saved))
        stale_removed = remove_stale_activities(db, rows)
        logger.info("stale activities removed: %d", stale_removed)
        removed = remove_duplicate_activities(db)
        logger.info("duplicate activities removed: %d", removed)
    except Exception:
        db.rollback()
        logger.exception("activity upsert failed")
    finally:
        db.close()

    counts = {}
    for row in rows:
        counts[row.source] = counts.get(row.source, 0) + 1
    logger.info("counts by source: %s", counts)

    _embed_new_activities()
    _refresh_recommendations()


def _embed_new_activities() -> None:
    from app.ai.embeddings.activity_embeddings import embed_pending_activities
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        count = embed_pending_activities(db)
        logger.info("activity embedding done: %d", count)
    except Exception:
        db.rollback()
        logger.exception("activity embedding failed")
    finally:
        db.close()


def _refresh_recommendations() -> None:
    from app.ai.recommendations.extracurricular_recommender import recommend_for_all_users
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        count = recommend_for_all_users(db)
        logger.info("recommendation refresh done: users=%d", count)
    except Exception:
        db.rollback()
        logger.exception("recommendation refresh failed")
    finally:
        db.close()


scheduler.add_job(
    _crawl_notice_boards,
    trigger=CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"),
    id="notice_board_daily",
    replace_existing=True,
)

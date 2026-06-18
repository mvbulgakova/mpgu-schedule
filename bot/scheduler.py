import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.config import settings

logger = logging.getLogger(__name__)


def create_scheduler(db_session_factory) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def _sync_job():
        from bot.services.data_sync import sync_all
        async with db_session_factory() as db:
            logger.info("Starting schedule sync...")
            await sync_all(db)

    scheduler.add_job(
        _sync_job,
        trigger="interval",
        hours=settings.poll_interval_hours,
        id="sync_schedules",
    )
    return scheduler

import logging
import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.config import settings
from bot.db.models import Institute, Schedule

logger = logging.getLogger(__name__)


def build_group_list(manifest: dict) -> list[dict]:
    return manifest.get("groups") or []


async def fetch_json(session: aiohttp.ClientSession, path: str) -> dict:
    url = f"{settings.cdn_base}/{path}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def sync_institute(
    db: AsyncSession,
    session: aiohttp.ClientSession,
    institute_id: str,
    institute_name: str,
) -> int:
    """Load all groups for one institute from CDN into DB. Returns group count."""
    try:
        manifest = await fetch_json(session, f"institutes/{institute_id}/schedule.json")
    except Exception as e:
        logger.warning("Failed to load manifest %s: %s", institute_id, e)
        return 0

    groups = build_group_list(manifest)
    count = 0

    for g in groups:
        filename = g.get("file") or g["name"]
        try:
            group_data = await fetch_json(
                session, f"institutes/{institute_id}/groups/{filename}.json"
            )
        except Exception as e:
            logger.warning("Failed to load group %s/%s: %s", institute_id, filename, e)
            continue

        stmt = pg_insert(Schedule).values(
            group_code=group_data["name"],
            institute_id=institute_id,
            data=group_data,
        ).on_conflict_do_update(
            index_elements=["group_code"],
            set_={"data": group_data},
        )
        await db.execute(stmt)
        count += 1

    stmt = pg_insert(Institute).values(
        id=institute_id,
        name=institute_name,
        groups_count=count,
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={"name": institute_name, "groups_count": count},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("Synced %s: %d groups", institute_id, count)
    return count


async def sync_all(db: AsyncSession) -> None:
    """Sync all enabled institutes from CDN."""
    async with aiohttp.ClientSession() as session:
        try:
            index = await fetch_json(session, "meta/index.json")
        except Exception as e:
            logger.error("Failed to load index.json: %s", e)
            return

        enabled = set(settings.enabled_institutes)
        for inst in index.get("institutes", []):
            if inst["id"] in enabled:
                await sync_institute(db, session, inst["id"], inst["name"])

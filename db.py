# ============================================
#  MongoDB Operations — Channel Management
#  With retry logic for network resilience
# ============================================

import asyncio
import logging
import motor.motor_asyncio
from datetime import datetime, timezone
from config import MONGO_URI, DB_NAME

logger = logging.getLogger(__name__)

# Per-event-loop Motor clients (fixes "Future attached to different loop" error)
_loop_clients: dict = {}

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def _get_db():
    """
    Returns a Motor DB client for the current event loop.
    Each event loop (bot thread / forwarder thread) gets its own client.
    """
    loop = asyncio.get_running_loop()
    if loop not in _loop_clients:
        client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        _loop_clients[loop] = client[DB_NAME]
    return _loop_clients[loop]


async def _retry(coro_func, *args, **kwargs):
    """
    Retry wrapper for DB operations.
    Retries up to MAX_RETRIES times with exponential backoff.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY * attempt
                logger.warning(f"[DB] Attempt {attempt}/{MAX_RETRIES} failed: {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"[DB] All {MAX_RETRIES} attempts failed: {e}")
                raise last_error


# ──────────────────────────────────────────────
#  Source Channels CRUD
# ──────────────────────────────────────────────

async def _add_channel_impl(channel_id: int, channel_title: str) -> bool:
    db = _get_db()
    existing = await db["source_channels"].find_one({"channel_id": channel_id})
    if existing:
        return False
    await db["source_channels"].insert_one({
        "channel_id": channel_id,
        "channel_title": channel_title,
        "added_at": datetime.now(timezone.utc).isoformat()
    })
    return True


async def add_channel(channel_id: int, channel_title: str) -> bool:
    """Adds a source channel. Returns True if new, False if already exists."""
    return await _retry(_add_channel_impl, channel_id, channel_title)


async def _remove_channel_impl(channel_id: int) -> bool:
    db = _get_db()
    result = await db["source_channels"].delete_one({"channel_id": channel_id})
    return result.deleted_count > 0


async def remove_channel(channel_id: int) -> bool:
    """Removes a specific channel. Returns True if removed, False if not found."""
    return await _retry(_remove_channel_impl, channel_id)


async def _remove_all_impl() -> int:
    db = _get_db()
    result = await db["source_channels"].delete_many({})
    return result.deleted_count


async def remove_all_channels() -> int:
    """Removes all source channels. Returns count of removed channels."""
    return await _retry(_remove_all_impl)


async def _get_all_impl() -> list:
    db = _get_db()
    channels = []
    async for doc in db["source_channels"].find({}, {"_id": 0}):
        channels.append(doc)
    return channels


async def get_all_channels() -> list:
    """Returns list of all source channels."""
    return await _retry(_get_all_impl)


async def _get_ids_impl() -> set:
    db = _get_db()
    ids = set()
    async for doc in db["source_channels"].find({}, {"channel_id": 1, "_id": 0}):
        ids.add(doc["channel_id"])
    return ids


async def get_channel_ids() -> set:
    """Returns set of channel IDs for quick lookup."""
    return await _retry(_get_ids_impl)


# ──────────────────────────────────────────────
#  Destination Channel Settings
# ──────────────────────────────────────────────

async def _set_dest_impl(channel_id: int, channel_title: str = ""):
    db = _get_db()
    await db["settings"].update_one(
        {"key": "destination"},
        {"$set": {
            "key": "destination",
            "channel_id": channel_id,
            "channel_title": channel_title,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )


async def set_destination(channel_id: int, channel_title: str = ""):
    """Sets the destination channel."""
    return await _retry(_set_dest_impl, channel_id, channel_title)


async def _get_dest_impl() -> dict | None:
    db = _get_db()
    doc = await db["settings"].find_one({"key": "destination"}, {"_id": 0, "key": 0})
    return doc


async def get_destination() -> dict | None:
    """Returns destination channel info, or None if not set."""
    return await _retry(_get_dest_impl)

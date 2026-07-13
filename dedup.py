# ============================================
#  Duplicate Detection — Same Post/Image Skip
#  Stores hashes in MongoDB + in-memory cache
#  If same text or image comes again → SKIP
# ============================================

import hashlib
import re
import logging
import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
from io import BytesIO

import db as db_module

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  In-Memory LRU Cache (fast lookups)
# ──────────────────────────────────────────────

class _DedupCache:
    """In-memory LRU cache for fast duplicate lookups."""

    def __init__(self, max_size: int = 2000):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size

    def exists(self, hash_key: str) -> bool:
        if hash_key in self._cache:
            self._cache.move_to_end(hash_key)
            return True
        return False

    def add(self, hash_key: str):
        if hash_key in self._cache:
            self._cache.move_to_end(hash_key)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            self._cache[hash_key] = True

    def load_bulk(self, hash_keys: list[str]):
        """Load multiple keys at once (used for startup from DB)."""
        for key in hash_keys:
            self.add(key)

    def __len__(self):
        return len(self._cache)


_cache = _DedupCache(max_size=2000)
_initialized = False


# ──────────────────────────────────────────────
#  Hash Computation
# ──────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """
    Normalize text for consistent hashing:
    - Lowercase
    - Remove extra whitespace
    - Remove emojis (they vary across platforms)
    - Strip leading/trailing whitespace
    """
    if not text:
        return ""
    # Lowercase
    text = text.lower().strip()
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove common emoji ranges (they cause false negatives)
    text = re.sub(
        r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FAFF]',
        '', text
    )
    return text.strip()


def compute_text_hash(text: str) -> str:
    """Compute hash of normalized text content."""
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()


def compute_image_hash(image_bytes: bytes) -> str:
    """Compute MD5 hash of image bytes for exact match."""
    if not image_bytes:
        return ""
    return hashlib.md5(image_bytes).hexdigest()


def compute_image_hash_from_bytesio(media_bytesio: BytesIO) -> str:
    """Compute image hash from BytesIO without consuming stream."""
    original_pos = media_bytesio.tell()
    media_bytesio.seek(0)
    image_bytes = media_bytesio.read()
    media_bytesio.seek(original_pos)
    return compute_image_hash(image_bytes)


# ──────────────────────────────────────────────
#  MongoDB Operations
# ──────────────────────────────────────────────

def _get_collection():
    """Get the dedup_hashes MongoDB collection."""
    database = db_module._get_db()
    return database["forwarded_hashes"]


async def _store_hash_in_db(content_hash: str, hash_type: str, preview: str = ""):
    """Store a hash in MongoDB."""
    try:
        collection = _get_collection()
        await collection.update_one(
            {"hash": content_hash},
            {"$set": {
                "hash": content_hash,
                "type": hash_type,  # "text" or "image"
                "preview": preview[:100],  # First 100 chars for debugging
                "forwarded_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
    except Exception as e:
        logger.error(f"[DEDUP] Failed to store hash in DB: {e}")


async def _hash_exists_in_db(content_hash: str) -> bool:
    """Check if hash exists in MongoDB."""
    try:
        collection = _get_collection()
        doc = await collection.find_one({"hash": content_hash}, {"_id": 1})
        return doc is not None
    except Exception as e:
        logger.error(f"[DEDUP] Failed to check hash in DB: {e}")
        return False


async def _load_recent_hashes(limit: int = 2000) -> list[str]:
    """Load recent hashes from MongoDB into memory cache."""
    try:
        collection = _get_collection()
        hashes = []
        cursor = collection.find(
            {},
            {"hash": 1, "_id": 0}
        ).sort("forwarded_at", -1).limit(limit)

        async for doc in cursor:
            hashes.append(doc["hash"])
        return hashes
    except Exception as e:
        logger.error(f"[DEDUP] Failed to load hashes from DB: {e}")
        return []


async def _ensure_indexes():
    """Create MongoDB indexes for fast lookups."""
    try:
        collection = _get_collection()
        # Unique index on hash for fast lookup
        await collection.create_index("hash", unique=True)
        # TTL index — auto-delete after 7 days (saves storage)
        await collection.create_index(
            "forwarded_at",
            expireAfterSeconds=7 * 24 * 60 * 60  # 7 days
        )
        logger.info("[DEDUP] MongoDB indexes created")
    except Exception as e:
        # Index might already exist — that's fine
        logger.debug(f"[DEDUP] Index creation note: {e}")


# ──────────────────────────────────────────────
#  Initialize — Load existing hashes from DB
# ──────────────────────────────────────────────

async def initialize_dedup():
    """
    Call this at bot startup.
    Loads recent hashes from MongoDB into memory cache.
    """
    global _initialized

    try:
        await _ensure_indexes()

        recent_hashes = await _load_recent_hashes()
        _cache.load_bulk(recent_hashes)

        _initialized = True
        logger.info(
            f"[DEDUP] Initialized — loaded {len(recent_hashes)} hashes from DB, "
            f"cache size: {len(_cache)}"
        )
    except Exception as e:
        logger.error(f"[DEDUP] Initialization error: {e}")
        _initialized = True  # Don't block forwarding on dedup failure


# ──────────────────────────────────────────────
#  Main API — Check & Mark Duplicates
# ──────────────────────────────────────────────

async def is_duplicate_text(text: str) -> bool:
    """
    Check if this text has been forwarded before.
    Returns True = duplicate (SKIP), False = new (FORWARD).
    """
    if not text or len(text.strip()) < 10:
        # Too short to meaningfully deduplicate
        return False

    text_hash = compute_text_hash(text)
    if not text_hash:
        return False

    # Check in-memory cache first (fast)
    if _cache.exists(text_hash):
        logger.info(f"[DEDUP] Duplicate text detected (cache hit): {text[:50]}...")
        return True

    # Check MongoDB (slower, but catches across restarts)
    if await _hash_exists_in_db(text_hash):
        _cache.add(text_hash)  # Add to memory cache for next time
        logger.info(f"[DEDUP] Duplicate text detected (DB hit): {text[:50]}...")
        return True

    return False


async def is_duplicate_image(image_bytes: bytes) -> bool:
    """
    Check if this image has been forwarded before.
    Returns True = duplicate (SKIP), False = new (FORWARD).
    """
    if not image_bytes:
        return False

    img_hash = compute_image_hash(image_bytes)
    if not img_hash:
        return False

    # Check in-memory cache first
    if _cache.exists(img_hash):
        logger.info(f"[DEDUP] Duplicate image detected (cache hit): hash={img_hash[:12]}")
        return True

    # Check MongoDB
    if await _hash_exists_in_db(img_hash):
        _cache.add(img_hash)
        logger.info(f"[DEDUP] Duplicate image detected (DB hit): hash={img_hash[:12]}")
        return True

    return False


async def is_duplicate_image_bytesio(media_bytesio: BytesIO) -> bool:
    """Convenience wrapper for BytesIO image data."""
    original_pos = media_bytesio.tell()
    media_bytesio.seek(0)
    image_bytes = media_bytesio.read()
    media_bytesio.seek(original_pos)
    return await is_duplicate_image(image_bytes)


async def mark_text_forwarded(text: str):
    """Mark this text as forwarded (store hash in cache + DB)."""
    if not text or len(text.strip()) < 10:
        return

    text_hash = compute_text_hash(text)
    if not text_hash:
        return

    _cache.add(text_hash)
    await _store_hash_in_db(text_hash, "text", preview=text[:100])


async def mark_image_forwarded(image_bytes: bytes):
    """Mark this image as forwarded (store hash in cache + DB)."""
    if not image_bytes:
        return

    img_hash = compute_image_hash(image_bytes)
    if not img_hash:
        return

    _cache.add(img_hash)
    await _store_hash_in_db(img_hash, "image", preview=f"image_{img_hash[:12]}")


async def mark_image_forwarded_bytesio(media_bytesio: BytesIO):
    """Convenience wrapper for BytesIO."""
    original_pos = media_bytesio.tell()
    media_bytesio.seek(0)
    image_bytes = media_bytesio.read()
    media_bytesio.seek(original_pos)
    await mark_image_forwarded(image_bytes)


# ──────────────────────────────────────────────
#  Stats (for admin bot)
# ──────────────────────────────────────────────

def get_dedup_stats() -> dict:
    """Returns dedup system stats."""
    return {
        "initialized": _initialized,
        "cache_size": len(_cache),
        "cache_max": 2000,
    }

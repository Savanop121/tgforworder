# ============================================
#  Forwarder — Telethon Userbot Message Forwarding
#  Features: Forward, Copy-forward (restricted),
#            Spoiler support, Album grouping,
#            Retry logic for network resilience
# ============================================

import asyncio
import logging
from io import BytesIO
from telethon import TelegramClient, events, errors
from config import API_ID, API_HASH, SESSION_NAME, CHANNEL_REFRESH_INTERVAL
import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 3  # seconds between retries

# Telethon userbot client
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# In-memory cache
_monitored_channels: set = set()
_destination_id: int | None = None
_main_loop: asyncio.AbstractEventLoop | None = None


# ──────────────────────────────────────────────
#  Retry Helper
# ──────────────────────────────────────────────

async def retry_operation(operation_name, coro, max_retries=MAX_RETRIES):
    """
    Retries an async operation up to max_retries times.
    Skips retry for permanent errors (restricted, unauthorized).
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return await coro()
        except (errors.ChatForwardsRestrictedError,
                errors.ChatWriteForbiddenError,
                errors.ChannelPrivateError,
                errors.UserBannedInChannelError) as e:
            # Permanent errors — no point retrying
            raise e
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = RETRY_DELAY * attempt
                logger.warning(
                    f"[RETRY] {operation_name} attempt {attempt}/{max_retries} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                await asyncio.sleep(wait)
            else:
                logger.error(f"[FAIL] {operation_name} failed after {max_retries} attempts: {e}")
                raise last_error


# ──────────────────────────────────────────────
#  Channel List Refresh (background task)
# ──────────────────────────────────────────────

async def refresh_channel_list():
    """Periodically refreshes the monitored channel list from MongoDB."""
    global _monitored_channels, _destination_id

    while True:
        try:
            _monitored_channels = await db.get_channel_ids()
            dest = await db.get_destination()
            _destination_id = dest.get("channel_id") if dest else None

            logger.info(
                f"[REFRESH] Channel list refreshed: {len(_monitored_channels)} sources, "
                f"destination: {_destination_id}"
            )
        except Exception as e:
            logger.error(f"[ERROR] Channel refresh error: {e}")

        await asyncio.sleep(CHANNEL_REFRESH_INTERVAL)


# ──────────────────────────────────────────────
#  Auto-Join Channel/Group
# ──────────────────────────────────────────────

async def auto_join_channel(channel_input):
    """
    Auto-joins a channel/group.
    Supports: channel ID, @username, invite links (t.me/+xxx, t.me/joinchat/xxx)
    Returns: (success: bool, title: str, channel_id: int)
    """
    try:
        input_str = str(channel_input).strip()

        # Handle private invite links
        if "t.me/+" in input_str or "t.me/joinchat/" in input_str:
            return await _join_via_invite(input_str)

        # Handle channel ID or @username
        return await _join_via_entity(channel_input)

    except Exception as e:
        logger.error(f"[ERROR] Auto-join error: {e}")
        return False, str(e), 0


async def _join_via_invite(input_str):
    """Joins a channel via private invite link."""
    from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest

    if "t.me/+" in input_str:
        invite_hash = input_str.split("t.me/+")[-1].strip("/")
    else:
        invite_hash = input_str.split("t.me/joinchat/")[-1].strip("/")

    try:
        result = await client(CheckChatInviteRequest(invite_hash))
        title = getattr(result, 'title', None) or getattr(
            getattr(result, 'chat', None), 'title', 'Unknown'
        )

        updates = await client(ImportChatInviteRequest(invite_hash))
        chat = updates.chats[0] if updates.chats else None
        if chat:
            channel_id = int(f"-100{chat.id}")
            return True, title, channel_id
        return False, title, 0

    except errors.UserAlreadyParticipantError:
        result = await client(CheckChatInviteRequest(invite_hash))
        chat = getattr(result, 'chat', None)
        if chat:
            title = getattr(chat, 'title', 'Unknown')
            return True, title, int(f"-100{chat.id}")
        return True, "Already Joined", 0

    except Exception as e:
        logger.error(f"[ERROR] Invite join failed: {e}")
        return False, str(e), 0


async def _join_via_entity(channel_input):
    """Joins a channel via ID or @username."""
    try:
        entity = await client.get_entity(channel_input)
        title = getattr(entity, 'title', None) or getattr(entity, 'username', None) or 'Unknown'

        if hasattr(entity, 'broadcast') or hasattr(entity, 'megagroup'):
            channel_id = int(f"-100{entity.id}")
        else:
            channel_id = -entity.id

    except (ValueError, errors.UsernameNotOccupiedError):
        # Entity not found
        return False, f"Could not find: {channel_input}", 0

    # Try to join
    try:
        from telethon.tl.functions.channels import JoinChannelRequest
        await client(JoinChannelRequest(entity))
        logger.info(f"[JOIN] Joined: {title}")
    except errors.UserAlreadyParticipantError:
        logger.info(f"[JOIN] Already member of: {title}")
    except Exception as e:
        logger.warning(f"[JOIN] Join attempt for {title}: {e}")

    return True, title, channel_id


def auto_join_channel_threadsafe(channel_input):
    """
    Thread-safe wrapper for auto_join_channel.
    Schedules the coroutine on the main event loop (where Telethon client lives).
    Safe to call from the bot thread.
    """
    if _main_loop is None:
        return False, "Forwarder not started yet", 0

    try:
        future = asyncio.run_coroutine_threadsafe(
            auto_join_channel(channel_input),
            _main_loop
        )
        return future.result(timeout=30)
    except TimeoutError:
        return False, "Operation timed out (30s)", 0
    except Exception as e:
        return False, str(e), 0


# ──────────────────────────────────────────────
#  Copy-Forward: For restricted channels
# ──────────────────────────────────────────────

async def copy_forward_message(message, destination):
    """
    Downloads media to RAM, then re-uploads as fresh content.
    Works for protected/restricted chats. Preserves spoiler flags.
    Cleans up RAM after upload.
    """
    media_bytes = None
    try:
        if message.media:
            spoiler = getattr(message.media, 'spoiler', False) or \
                      getattr(message.media, 'has_spoiler', False)
            caption = message.text or ""

            # Download media to bytes in memory
            media_bytes = BytesIO()
            await client.download_media(message, file=media_bytes)

            if media_bytes.tell() == 0:
                logger.warning("[WARN] Downloaded 0 bytes, skipping media")
                return False

            media_bytes.seek(0)
            media_bytes.name = _get_filename(message.media)

            # Re-upload as fresh content
            await client.send_file(
                destination,
                file=media_bytes,
                caption=caption,
                formatting_entities=message.entities,
                has_spoiler=spoiler
            )

        elif message.text:
            await client.send_message(
                destination,
                message.text,
                formatting_entities=message.entities
            )
        return True
    except Exception as e:
        logger.error(f"[ERROR] Copy-forward error: {e}")
        return False
    finally:
        # Always cleanup RAM
        if media_bytes:
            media_bytes.close()
            del media_bytes


async def copy_forward_album(messages, destination):
    """
    Downloads all album media to bytes, then re-uploads as a fresh album.
    Works for protected/restricted chats. Cleans up RAM after upload.
    """
    files = []
    try:
        captions = []

        for msg in messages:
            if msg.media:
                media_bytes = BytesIO()
                await client.download_media(msg, file=media_bytes)

                if media_bytes.tell() == 0:
                    media_bytes.close()
                    continue

                media_bytes.seek(0)
                media_bytes.name = _get_filename(msg.media)

                files.append(media_bytes)
                captions.append(msg.text or "")

        if files:
            await client.send_file(
                destination,
                file=files,
                caption=captions
            )
        return True
    except Exception as e:
        logger.error(f"[ERROR] Copy-forward album error: {e}")
        return False
    finally:
        # Always cleanup all buffers from RAM
        for f in files:
            try:
                f.close()
            except Exception:
                pass


def _get_filename(media):
    """Extracts filename from media for proper file type detection."""
    if hasattr(media, 'document') and media.document:
        for attr in media.document.attributes:
            if hasattr(attr, 'file_name'):
                return attr.file_name
    if hasattr(media, 'photo'):
        return "photo.jpg"
    return "file"


# ──────────────────────────────────────────────
#  Smart Forward — tries forward first, falls back to copy
#  With retry logic
# ──────────────────────────────────────────────

async def smart_forward(message, destination):
    """
    Tries normal forward first. If restricted, falls back to copy-forward.
    Retries on network errors.
    """
    async def _do_forward():
        try:
            await client.forward_messages(entity=destination, messages=message)
            return "forwarded"
        except errors.ChatForwardsRestrictedError:
            success = await copy_forward_message(message, destination)
            return "copied" if success else "failed"

    try:
        return await retry_operation("Forward", _do_forward)
    except (errors.ChatForwardsRestrictedError,
            errors.ChatWriteForbiddenError,
            errors.ChannelPrivateError):
        # Try copy as last resort for permanent forward errors
        success = await copy_forward_message(message, destination)
        return "copied" if success else "failed"
    except Exception as e:
        logger.error(f"[ERROR] Smart forward failed: {e}")
        # Last resort: try copy
        try:
            success = await copy_forward_message(message, destination)
            return "copied" if success else "failed"
        except Exception:
            return "failed"


async def smart_forward_album(messages, destination):
    """
    Album smart forward with retry and copy fallback.
    """
    async def _do_forward_album():
        try:
            await client.forward_messages(entity=destination, messages=messages)
            return "forwarded"
        except errors.ChatForwardsRestrictedError:
            success = await copy_forward_album(messages, destination)
            return "copied" if success else "failed"

    try:
        return await retry_operation("Album Forward", _do_forward_album)
    except (errors.ChatForwardsRestrictedError,
            errors.ChatWriteForbiddenError,
            errors.ChannelPrivateError):
        success = await copy_forward_album(messages, destination)
        return "copied" if success else "failed"
    except Exception as e:
        logger.error(f"[ERROR] Smart album forward failed: {e}")
        try:
            success = await copy_forward_album(messages, destination)
            return "copied" if success else "failed"
        except Exception:
            return "failed"


# ──────────────────────────────────────────────
#  New Message Event Handler
# ──────────────────────────────────────────────

@client.on(events.NewMessage())
async def on_new_message(event):
    """Handles single messages. Skips album parts (handled by on_album)."""
    global _destination_id

    try:
        # Skip album messages — on_album handler will handle them
        if event.message.grouped_id:
            return

        chat_id = event.chat_id

        if chat_id not in _monitored_channels:
            return

        if _destination_id is None:
            return  # Silently skip if no destination

        # Smart forward with retry
        result = await smart_forward(event.message, _destination_id)

        chat = await event.get_chat()
        chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(chat_id)
        msg_type = "media" if event.message.media else "text"
        logger.info(f"[FWD] {result} {msg_type} from [{chat_title}] to destination")

    except Exception as e:
        logger.error(f"[ERROR] Message handler error: {e}")


# ──────────────────────────────────────────────
#  Album (Grouped Media) Handler
# ──────────────────────────────────────────────

@client.on(events.Album())
async def on_album(event):
    """Handles grouped media (albums). Forwards all items together."""
    global _destination_id

    try:
        chat_id = event.chat_id

        if chat_id not in _monitored_channels:
            return

        if _destination_id is None:
            return

        result = await smart_forward_album(event.messages, _destination_id)

        chat = await event.get_chat()
        chat_title = getattr(chat, 'title', None) or str(chat_id)
        logger.info(f"[FWD] {result} album ({len(event.messages)} items) from [{chat_title}]")

    except Exception as e:
        logger.error(f"[ERROR] Album handler error: {e}")


# ──────────────────────────────────────────────
#  Start Forwarder
# ──────────────────────────────────────────────

async def start_forwarder():
    """
    Starts the Telethon client and channel list refresh loop.
    First run will ask for phone number + OTP for session login.
    """
    global _main_loop
    _main_loop = asyncio.get_running_loop()

    logger.info("Starting Telethon Forwarder...")

    # Connect and login with retry
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await client.start()
            break
        except Exception as e:
            if attempt < MAX_RETRIES:
                logger.warning(f"[RETRY] Connection attempt {attempt}/{MAX_RETRIES} failed: {e}")
                await asyncio.sleep(RETRY_DELAY * attempt)
            else:
                logger.error(f"[FAIL] Could not connect after {MAX_RETRIES} attempts")
                raise

    me = await client.get_me()
    logger.info(f"[OK] Logged in as: {me.first_name} (@{me.username})")

    # Initial channel list load
    global _monitored_channels, _destination_id
    _monitored_channels = await db.get_channel_ids()
    dest = await db.get_destination()
    _destination_id = dest.get("channel_id") if dest else None

    logger.info(f"Monitoring {len(_monitored_channels)} channels")
    logger.info(f"Destination: {_destination_id}")

    # Start background refresh task
    asyncio.create_task(refresh_channel_list())

    logger.info("Listening for new messages...")

    # Keep running
    await client.run_until_disconnected()

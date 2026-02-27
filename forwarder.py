# ============================================
#  Forwarder — Telethon Userbot Message Forwarding
#  Features: Forward, Copy-forward (restricted),
#            Spoiler support, Album grouping,
#            Footer replace, Ad filter, Retry logic
# ============================================

import asyncio
import logging
from io import BytesIO
from telethon import TelegramClient, events, errors
from config import API_ID, API_HASH, SESSION_NAME, CHANNEL_REFRESH_INTERVAL, CUSTOM_FOOTER
import db
from message_filter import process_message_text, is_ad_or_spam

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 3

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
    Skips retry for permanent errors.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return await coro()
        except (errors.ChatForwardsRestrictedError,
                errors.ChatWriteForbiddenError,
                errors.ChannelPrivateError,
                errors.UserBannedInChannelError) as e:
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
#  Channel List Refresh
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
    Supports: channel ID, @username, invite links
    Returns: (success: bool, title: str, channel_id: int)
    """
    try:
        input_str = str(channel_input).strip()
        if "t.me/+" in input_str or "t.me/joinchat/" in input_str:
            return await _join_via_invite(input_str)
        return await _join_via_entity(channel_input)
    except Exception as e:
        logger.error(f"[ERROR] Auto-join error: {e}")
        return False, str(e), 0


async def _join_via_invite(input_str):
    """Joins via private invite link."""
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
            return True, title, int(f"-100{chat.id}")
        return False, title, 0
    except errors.UserAlreadyParticipantError:
        result = await client(CheckChatInviteRequest(invite_hash))
        chat = getattr(result, 'chat', None)
        if chat:
            return True, getattr(chat, 'title', 'Unknown'), int(f"-100{chat.id}")
        return True, "Already Joined", 0
    except Exception as e:
        logger.error(f"[ERROR] Invite join failed: {e}")
        return False, str(e), 0


async def _join_via_entity(channel_input):
    """Joins via channel ID or @username."""
    try:
        entity = await client.get_entity(channel_input)
        title = getattr(entity, 'title', None) or getattr(entity, 'username', None) or 'Unknown'
        if hasattr(entity, 'broadcast') or hasattr(entity, 'megagroup'):
            channel_id = int(f"-100{entity.id}")
        else:
            channel_id = -entity.id
    except (ValueError, errors.UsernameNotOccupiedError):
        return False, f"Could not find: {channel_input}", 0

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
    """Thread-safe wrapper — schedules on main event loop."""
    if _main_loop is None:
        return False, "Forwarder not started yet", 0
    try:
        future = asyncio.run_coroutine_threadsafe(
            auto_join_channel(channel_input), _main_loop
        )
        return future.result(timeout=30)
    except TimeoutError:
        return False, "Operation timed out (30s)", 0
    except Exception as e:
        return False, str(e), 0


# ──────────────────────────────────────────────
#  Helper: Filename extraction
# ──────────────────────────────────────────────

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
#  Copy-Forward with Footer Replacement
#  Always uses copy mode so text can be modified
# ──────────────────────────────────────────────

async def copy_forward_message(message, destination):
    """
    Downloads media to RAM, modifies caption (footer replace),
    then re-uploads as fresh content. Preserves spoiler flags.
    """
    media_bytes = None
    try:
        # Process text — ad/welcome filter + footer replace
        original_text = message.text or ""
        processed_text = process_message_text(original_text, CUSTOM_FOOTER)

        # None means skip (ad or welcome message)
        if processed_text is None:
            return "skipped"

        if message.media:
            spoiler = getattr(message.media, 'spoiler', False) or \
                      getattr(message.media, 'has_spoiler', False)

            # Download media
            media_bytes = BytesIO()
            await client.download_media(message, file=media_bytes)

            if media_bytes.tell() == 0:
                logger.warning("[WARN] Downloaded 0 bytes, skipping media")
                return "failed"

            media_bytes.seek(0)
            media_bytes.name = _get_filename(message.media)

            # Re-upload with modified caption
            await client.send_file(
                destination,
                file=media_bytes,
                caption=processed_text,
                has_spoiler=spoiler
            )
        elif processed_text:
            await client.send_message(
                destination,
                processed_text
            )
        return "copied"
    except Exception as e:
        logger.error(f"[ERROR] Copy-forward error: {e}")
        return "failed"
    finally:
        if media_bytes:
            media_bytes.close()
            del media_bytes


async def copy_forward_album(messages, destination):
    """
    Downloads all album media, modifies captions, re-uploads as album.
    """
    files = []
    try:
        captions = []

        # Check first message text for ad/welcome
        first_text = ""
        for msg in messages:
            if msg.text:
                first_text += msg.text + "\n"

        if first_text and is_ad_or_spam(first_text):
            logger.info("[FILTER] Album ad detected, skipping")
            return "skipped"

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

                # Footer replace on caption
                cap = msg.text or ""
                if cap:
                    processed = process_message_text(cap, CUSTOM_FOOTER)
                    captions.append(processed if processed else "")
                else:
                    captions.append("")

        if files:
            # Add custom footer to last caption if no caption has it yet
            has_footer = any(CUSTOM_FOOTER.strip()[:20] in c for c in captions if c)
            if not has_footer and captions:
                last_idx = len(captions) - 1
                if captions[last_idx]:
                    captions[last_idx] = f"{captions[last_idx]}\n\n{CUSTOM_FOOTER.strip()}"
                else:
                    captions[last_idx] = CUSTOM_FOOTER.strip()

            await client.send_file(
                destination,
                file=files,
                caption=captions
            )
        return "copied"
    except Exception as e:
        logger.error(f"[ERROR] Copy-forward album error: {e}")
        return "failed"
    finally:
        for f in files:
            try:
                f.close()
            except Exception:
                pass


# ──────────────────────────────────────────────
#  Smart Forward — always copy mode for footer replacement
# ──────────────────────────────────────────────

async def smart_forward(message, destination):
    """
    Uses copy mode to forward (so footer can be replaced).
    Retries on network errors.
    """
    async def _do_forward():
        return await copy_forward_message(message, destination)

    try:
        return await retry_operation("Forward", _do_forward)
    except Exception as e:
        logger.error(f"[ERROR] Smart forward failed: {e}")
        return "failed"


async def smart_forward_album(messages, destination):
    """Album forward with retry."""
    async def _do_forward():
        return await copy_forward_album(messages, destination)

    try:
        return await retry_operation("Album Forward", _do_forward)
    except Exception as e:
        logger.error(f"[ERROR] Smart album forward failed: {e}")
        return "failed"


# ──────────────────────────────────────────────
#  New Message Event Handler
# ──────────────────────────────────────────────

@client.on(events.NewMessage())
async def on_new_message(event):
    """Handles single messages. Skips album parts."""
    global _destination_id

    try:
        if event.message.grouped_id:
            return

        chat_id = event.chat_id
        if chat_id not in _monitored_channels:
            return
        if _destination_id is None:
            return

        result = await smart_forward(event.message, _destination_id)

        if result == "skipped":
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', None) or str(chat_id)
            logger.info(f"[SKIP] Ad/welcome message from [{chat_title}]")
            return

        chat = await event.get_chat()
        chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(chat_id)
        msg_type = "media" if event.message.media else "text"
        logger.info(f"[FWD] {result} {msg_type} from [{chat_title}] to destination")

    except Exception as e:
        logger.error(f"[ERROR] Message handler error: {e}")


# ──────────────────────────────────────────────
#  Album Handler
# ──────────────────────────────────────────────

@client.on(events.Album())
async def on_album(event):
    """Handles grouped media (albums)."""
    global _destination_id

    try:
        chat_id = event.chat_id
        if chat_id not in _monitored_channels:
            return
        if _destination_id is None:
            return

        result = await smart_forward_album(event.messages, _destination_id)

        if result == "skipped":
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', None) or str(chat_id)
            logger.info(f"[SKIP] Ad/welcome album from [{chat_title}]")
            return

        chat = await event.get_chat()
        chat_title = getattr(chat, 'title', None) or str(chat_id)
        logger.info(f"[FWD] {result} album ({len(event.messages)} items) from [{chat_title}]")

    except Exception as e:
        logger.error(f"[ERROR] Album handler error: {e}")


# ──────────────────────────────────────────────
#  Start Forwarder
# ──────────────────────────────────────────────

async def start_forwarder():
    """Starts the Telethon client and channel list refresh loop."""
    global _main_loop
    _main_loop = asyncio.get_running_loop()

    logger.info("Starting Telethon Forwarder...")

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

    global _monitored_channels, _destination_id
    _monitored_channels = await db.get_channel_ids()
    dest = await db.get_destination()
    _destination_id = dest.get("channel_id") if dest else None

    logger.info(f"Monitoring {len(_monitored_channels)} channels")
    logger.info(f"Destination: {_destination_id}")

    asyncio.create_task(refresh_channel_list())
    logger.info("Listening for new messages...")

    await client.run_until_disconnected()

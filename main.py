# ============================================
#  Main Entry Point — Bot + Forwarder
# ============================================

import asyncio
import logging
import sys
import os
import threading

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Logging config BEFORE imports so all warnings are suppressed
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress noisy loggers — only WARNING+ level shown
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

# NOW import after logging is configured
from bot import build_bot_app
from forwarder import start_forwarder


def run_bot_in_thread():
    """
    Runs the admin bot in a separate thread.
    Uses manual initialization to avoid Linux signal handler issues.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run_bot():
        bot_app = build_bot_app()
        async with bot_app:
            await bot_app.updater.start_polling(drop_pending_updates=True)
            await bot_app.start()
            logger.info("Admin Bot started successfully")
            # Keep running until thread is killed
            while True:
                await asyncio.sleep(3600)

    try:
        loop.run_until_complete(_run_bot())
    except Exception as e:
        logger.error(f"Bot thread error: {e}")
    finally:
        loop.close()


async def main():
    """
    Main function — Runs both Bot and Forwarder simultaneously.
    """
    print("=" * 50)
    print("  TELEGRAM FORWARDER SCRIPT")
    print("=" * 50)
    print()
    print("  Features:")
    print("     - Forward messages from multiple channels")
    print("     - Text, Images, Videos, Documents - everything")
    print("     - Manage channels via Admin Bot")
    print("     - Data stored in MongoDB")
    print()
    print("  Commands (send in Bot):")
    print("     /start  - Open admin panel")
    print("     /myid   - View your Telegram ID")
    print("     /cancel - Cancel current action")
    print()
    print("=" * 50)

    # Start admin bot in a separate thread
    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    logger.info("Admin Bot started in background thread")

    # Start forwarder in main async loop
    await start_forwarder()



if __name__ == "__main__":
    asyncio.run(main())

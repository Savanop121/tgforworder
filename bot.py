# ============================================
#  Admin Bot — Channel Management Panel
# ============================================

import asyncio
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from config import BOT_TOKEN, ADMIN_IDS
import db
from forwarder import auto_join_channel_threadsafe

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
WAITING_CHANNEL_ID = 1
WAITING_DESTINATION = 2


# ──────────────────────────────────────────────
#  Helper: Admin check
# ──────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    """Check if user is admin. If ADMIN_IDS is empty, allow everyone."""
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


# ──────────────────────────────────────────────
#  Main Menu
# ──────────────────────────────────────────────

def get_main_menu():
    keyboard = [
        [
            InlineKeyboardButton("➕ Add Channel", callback_data="add_channel"),
            InlineKeyboardButton("📋 List Channels", callback_data="list_channels"),
        ],
        [
            InlineKeyboardButton("❌ Remove Channel", callback_data="remove_channel"),
            InlineKeyboardButton("🗑 Remove All", callback_data="remove_all"),
        ],
        [
            InlineKeyboardButton("🎯 Set Destination", callback_data="set_destination"),
            InlineKeyboardButton("📍 Show Destination", callback_data="show_destination"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ──────────────────────────────────────────────
#  /start Command
# ──────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized! Only admin can use this bot.")
        return

    await update.message.reply_text(
        "🤖 **Telegram Forwarder Admin Panel**\n\n"
        "Use this bot to manage your source channels.\n"
        "Select an action from the buttons below:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )


# ──────────────────────────────────────────────
#  /myid Command — Get your Telegram ID
# ──────────────────────────────────────────────

async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Your Telegram ID: `{update.effective_user.id}`",
        parse_mode="Markdown"
    )


# ──────────────────────────────────────────────
#  Callback: Add Channel
# ──────────────────────────────────────────────

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized!")
        return

    context.user_data["action"] = "add_channel"
    await query.edit_message_text(
        "**Add Channel**\n\n"
        "Send any one of the following:\n"
        "1. Channel ID: `-1001234567890`\n"
        "2. Username: `@channelname`\n"
        "3. Invite link: `https://t.me/+xxxxx`\n\n"
        "Bot will automatically join and add the channel!\n\n"
        "Cancel: /cancel",
        parse_mode="Markdown"
    )


# ──────────────────────────────────────────────
#  Callback: List Channels
# ──────────────────────────────────────────────

async def list_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized!")
        return

    channels = await db.get_all_channels()

    if not channels:
        await query.edit_message_text(
            "📭 No source channels added yet.\n\n"
            "➕ Use /start to add a channel.",
            parse_mode="Markdown"
        )
        return

    text = "📋 **Added Source Channels:**\n\n"
    for i, ch in enumerate(channels, 1):
        title = ch.get("channel_title", "Unknown")
        cid = ch["channel_id"]
        text += f"{i}. **{title}**\n   `{cid}`\n\n"

    text += f"📊 Total: {len(channels)} channels"

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ──────────────────────────────────────────────
#  Callback: Remove Channel (selection list)
# ──────────────────────────────────────────────

async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized!")
        return

    channels = await db.get_all_channels()

    if not channels:
        await query.edit_message_text(
            "📭 No channels to remove.\n\n"
            "➕ Use /start to add a channel first."
        )
        return

    keyboard = []
    for ch in channels:
        title = ch.get("channel_title", "Unknown")
        cid = ch["channel_id"]
        btn_text = f"❌ {title} ({cid})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"rm_{cid}")])

    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")])

    await query.edit_message_text(
        "🗑 **Which channel do you want to remove?**\n"
        "Select from below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ──────────────────────────────────────────────
#  Callback: Remove specific channel (rm_{id})
# ──────────────────────────────────────────────

async def remove_specific_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized!")
        return

    channel_id = int(query.data.replace("rm_", ""))
    removed = await db.remove_channel(channel_id)

    if removed:
        await query.edit_message_text(
            f"✅ Channel `{channel_id}` has been removed successfully!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
            )
        )
    else:
        await query.edit_message_text(
            f"❌ Channel `{channel_id}` not found.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
            )
        )


# ──────────────────────────────────────────────
#  Callback: Remove All Channels
# ──────────────────────────────────────────────

async def remove_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized!")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Remove All", callback_data="confirm_remove_all"),
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu"),
        ]
    ]
    await query.edit_message_text(
        "⚠️ **Are you sure you want to remove ALL channels?**\n\n"
        "This action cannot be undone!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def confirm_remove_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    count = await db.remove_all_channels()
    await query.edit_message_text(
        f"🗑 **{count} channels have been removed!**",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
        )
    )


# ──────────────────────────────────────────────
#  Callback: Set Destination
# ──────────────────────────────────────────────

async def set_destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized!")
        return

    context.user_data["action"] = "set_destination"
    await query.edit_message_text(
        "🎯 **Set Destination Channel**\n\n"
        "Send the ID of the channel where messages should be forwarded.\n"
        "(Example: `-1001234567890`)\n\n"
        "Cancel: /cancel",
        parse_mode="Markdown"
    )


# ──────────────────────────────────────────────
#  Callback: Show Destination
# ──────────────────────────────────────────────

async def show_destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized!")
        return

    dest = await db.get_destination()

    if dest:
        title = dest.get("channel_title", "N/A")
        cid = dest.get("channel_id", "Not Set")
        text = (
            f"📍 **Current Destination Channel:**\n\n"
            f"📛 Title: **{title}**\n"
            f"🆔 ID: `{cid}`"
        )
    else:
        text = "📍 Destination channel is not set yet.\n🎯 Please set a destination first!"

    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ──────────────────────────────────────────────
#  Callback: Back to Main Menu
# ──────────────────────────────────────────────

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Clear any pending action
    context.user_data.pop("action", None)

    await query.edit_message_text(
        "🤖 **Telegram Forwarder Admin Panel**\n\n"
        "Select an action from the buttons below:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )


# ──────────────────────────────────────────────
#  Message Handler: Process user text input
# ──────────────────────────────────────────────

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Channel posts have no effective_user — skip them
    if not update.effective_user:
        return
    if not update.message or not update.message.text:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized!")
        return

    action = context.user_data.get("action")
    text = update.message.text.strip()

    if action == "add_channel":
        context.user_data.pop("action", None)
        await _process_add_channel(update, text)

    elif action == "set_destination":
        context.user_data.pop("action", None)
        await _process_set_destination(update, text)

    else:
        await update.message.reply_text(
            "🤔 Didn't understand. Use /start to open the menu.",
            reply_markup=get_main_menu()
        )


async def _process_add_channel(update: Update, text: str):
    """Adds a channel via ID, username, or invite link. Auto-joins the channel."""
    try:
        input_text = text.strip()

        # Determine input type
        is_invite = "t.me/+" in input_text or "t.me/joinchat/" in input_text
        is_username = input_text.startswith("@")
        is_id = input_text.lstrip("-").isdigit()

        if not is_invite and not is_username and not is_id:
            await update.message.reply_text(
                "Invalid format! Please send one of:\n"
                "- Channel ID: `-1001234567890`\n"
                "- Username: `@channelname`\n"
                "- Invite: `https://t.me/+xxxxx`",
                parse_mode="Markdown"
            )
            return

        await update.message.reply_text("Joining channel... please wait...")

        # Parse input for auto_join
        if is_id:
            channel_input = int(input_text)
        elif is_username:
            channel_input = input_text
        else:
            channel_input = input_text  # invite link

        # Auto-join the channel (thread-safe — runs on main event loop)
        success, title, resolved_id = await asyncio.to_thread(
            auto_join_channel_threadsafe, channel_input
        )

        if not success:
            await update.message.reply_text(
                f"Failed to join channel: {title}\n"
                "Please check if the link/ID is correct.",
                reply_markup=get_main_menu()
            )
            return

        # Use resolved ID if available, otherwise use input ID
        final_id = resolved_id if resolved_id else (channel_input if is_id else 0)

        if not final_id:
            await update.message.reply_text(
                f"Channel joined ({title}) but ID could not be resolved.\n"
                "Please try using a numeric ID.",
                reply_markup=get_main_menu()
            )
            return

        # Add to MongoDB
        added = await db.add_channel(final_id, title)

        if added:
            await update.message.reply_text(
                f"Channel joined + added!\n\n"
                f"Name: **{title}**\n"
                f"ID: `{final_id}`\n\n"
                f"Messages from this channel will now be forwarded.",
                parse_mode="Markdown",
                reply_markup=get_main_menu()
            )
        else:
            await update.message.reply_text(
                f"Channel `{final_id}` ({title}) is already added!",
                parse_mode="Markdown",
                reply_markup=get_main_menu()
            )

    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}\nPlease try again.",
            reply_markup=get_main_menu()
        )


async def _process_set_destination(update: Update, text: str):
    """Set destination channel."""
    try:
        channel_id = int(text)
        await db.set_destination(channel_id, f"Destination {channel_id}")
        await update.message.reply_text(
            f"✅ Destination channel set to: `{channel_id}`\n\n"
            f"All source channel messages will now be forwarded here!",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid ID! Please enter numbers only.\nExample: `-1001234567890`",
            parse_mode="Markdown"
        )


# ──────────────────────────────────────────────
#  /cancel Command
# ──────────────────────────────────────────────

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("action", None)
    await update.message.reply_text(
        "❌ Action cancelled.\nUse /start to open the menu.",
        reply_markup=get_main_menu()
    )


# ──────────────────────────────────────────────
#  Error Handler
# ──────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Silently handles bot errors."""
    error = context.error
    # Skip network errors — bot will automatically retry
    error_name = type(error).__name__
    if "NetworkError" in error_name or "TimedOut" in error_name or "ConnectError" in error_name:
        return
    logger.error(f"Bot error: {error}")


# ──────────────────────────────────────────────
#  Build Bot Application
# ──────────────────────────────────────────────

def build_bot_app() -> Application:
    """Builds the bot application with all handlers."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # Callback queries (inline buttons)
    app.add_handler(CallbackQueryHandler(add_channel_callback, pattern="^add_channel$"))
    app.add_handler(CallbackQueryHandler(list_channels_callback, pattern="^list_channels$"))
    app.add_handler(CallbackQueryHandler(remove_channel_callback, pattern="^remove_channel$"))
    app.add_handler(CallbackQueryHandler(remove_all_callback, pattern="^remove_all$"))
    app.add_handler(CallbackQueryHandler(confirm_remove_all, pattern="^confirm_remove_all$"))
    app.add_handler(CallbackQueryHandler(set_destination_callback, pattern="^set_destination$"))
    app.add_handler(CallbackQueryHandler(show_destination_callback, pattern="^show_destination$"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(remove_specific_channel, pattern=r"^rm_-?\d+$"))

    # Text message handler (for add channel / set destination input)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    # Error handler — no more "No error handlers registered" spam
    app.add_error_handler(error_handler)

    return app

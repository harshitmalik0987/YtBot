# bot.py
import os
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import config
import utils

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message."""
    await update.message.reply_text(
        "👋 Hi! Send me a video link and I'll download it for you.\n"
        "I will offer the top 3 video qualities and an audio option."
    )

# Handle regular messages (assume they are URLs to download)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Indicate bot is processing
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        # Fetch video info
        info = utils.get_video_info(url)
        title = info.get("title", "video")
        # Select formats (3 video + 1 audio)
        formats = utils.select_formats(info, num_formats=3)
        if not formats:
            await update.message.reply_text("⚠️ No downloadable formats found.")
            return

        # Build inline keyboard with format options
        keyboard = []
        for f in formats:
            fmt_id = f.get("format_id")
            # Label: e.g. "720p MP4" or "Audio (MP3)"
            if f.get("vcodec") != "none":
                # Video format
                height = f.get("height") or f.get("resolution") or ""
                ext = f.get("ext", "")
                label = f"{height}p {ext.upper()}"
            else:
                # Audio-only format
                abr = f.get("abr") or ""
                ext = f.get("ext", "")
                label = f"🔊 Audio {ext.upper()} ({int(abr)} kbps)"
            keyboard.append([InlineKeyboardButton(label, callback_data=fmt_id)])
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Store info in user_data for callback reference
        context.user_data['info'] = {"url": url, "title": title}
        context.user_data['formats'] = {f.get("format_id"): f for f in formats}

        await update.message.reply_text(
            f"🎬 *Select format for:* {title}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error("Error fetching info: %s", e)
        await update.message.reply_text(f"❌ Failed to retrieve video info: {e}")

# Handle format selection via inline button
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    fmt_id = query.data
    chat_id = query.message.chat.id

    # Retrieve stored URL and formats
    info = context.user_data.get('info')
    formats = context.user_data.get('formats', {})
    if not info or fmt_id not in formats:
        await query.edit_message_text("⚠️ Format selection error. Please try again.")
        return

    url = info['url']
    title = info['title']
    selected_fmt = formats[fmt_id]

    # Edit previous message to show we are downloading
    await query.edit_message_text(f"⬇️ Downloading *{title}* in format {fmt_id}...", parse_mode="Markdown")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)

    try:
        # Ensure download directory exists
        os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
        # Download the selected format
        filepath = utils.download_format(url, fmt_id, config.DOWNLOAD_DIR)

        # Check file size
        file_size = os.path.getsize(filepath)
        if file_size <= 50 * 1024 * 1024:
            # Send file directly to Telegram
            await context.bot.send_video(chat_id=chat_id, video=open(filepath, 'rb'), caption=title)
            # Optionally delete file after sending
            os.remove(filepath)
        else:
            # File too large: send a download link instead
            filename = os.path.basename(filepath)
            download_url = f"{config.BASE_URL}{filename}"
            await query.message.reply_text(
                f"💾 File is large ({file_size // (1024*1024)} MB). Download it here:\n{download_url}"
            )
            # (Optional) leave file in downloads directory or schedule deletion later
    except Exception as e:
        logger.error("Error downloading/sending file: %s", e)
        await query.message.reply_text(f"❌ Download failed: {e}")

# Error handler to catch exceptions
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if update and getattr(update, "message", None):
        await update.message.reply_text("⚠️ An unexpected error occurred.")

def main():
    # Start the HTTP server for large-file links
    utils.start_http_server(config.DOWNLOAD_DIR, config.HOST, config.PORT)

    # Create the Telegram application
    app = Application.builder().token(config.TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    # Any text message (assuming URL to download)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # Inline button callback
    app.add_handler(CallbackQueryHandler(button_handler))
    # Global error handler
    app.add_error_handler(error_handler)

    # Run the bot
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
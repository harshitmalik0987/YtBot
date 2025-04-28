import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ChatAction

import config
from utils import start_http_server, get_top_formats, download_media

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /start command. Welcomes the user.
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    welcome_text = (
        "👋 Hi! Send me a video URL and I'll provide download options. "
        "I can send files up to 50MB directly, or share a link for larger files."
    )
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /help command. Explains usage.
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    help_text = (
        "📥 Just send me a video or audio link (e.g., YouTube, Twitter, etc.). "
        "I will list available formats to download."
    )
    await update.message.reply_text(help_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle text messages (expects a URL). Fetches format options.
    """
    text = update.message.text.strip()
    # Basic URL validation
    if not text.startswith("http://") and not text.startswith("https://"):
        await update.message.reply_text("❌ Please send a valid URL (starting with http:// or https://).")
        return

    url = text
    context.user_data['url'] = url

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        video_list, audio_format = get_top_formats(url)
    except Exception as e:
        await update.message.reply_text(
            "❌ Could not fetch video info. Please ensure the URL is correct and try again."
        )
        return

    if not video_list:
        await update.message.reply_text("❌ No suitable video formats found.")
        return

    # Build inline keyboard with format options
    buttons = []
    for fmt in video_list:
        res = fmt.get('height', 0)
        ext = fmt.get('ext', '')
        text_btn = f"📹 {res}p ({ext})"
        callback_data = f"video_{fmt['format_id']}"
        buttons.append(InlineKeyboardButton(text_btn, callback_data=callback_data))

    if audio_format:
        abr = audio_format.get('abr', 0)
        ext = audio_format.get('ext', '')
        text_btn = f"🎵 Audio ({ext}, {abr}kbps)"
        callback_data = f"audio_{audio_format['format_id']}"
        buttons.append(InlineKeyboardButton(text_btn, callback_data=callback_data))

    # Arrange buttons in two columns
    keyboard = []
    for i in range(0, len(buttons), 2):
        keyboard.append(buttons[i:i+2])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose a format to download:", reply_markup=reply_markup)

    # Store format info for callback usage
    context.user_data['video_list'] = video_list
    context.user_data['audio_format'] = audio_format

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle button clicks from the inline keyboard. Downloads the chosen format.
    """
    query = update.callback_query
    await query.answer()

    data = query.data  # e.g. "video_137" or "audio_251"
    chat_id = query.message.chat.id

    # Edit the message to indicate processing
    await query.edit_message_text("⏳ Downloading your file, please wait...")

    url = context.user_data.get('url')
    if not url:
        await query.message.reply_text("❌ URL not found. Please send a new link.")
        return

    # Determine if video or audio was requested
    if data.startswith("video_"):
        fmt_id = data.split("_", 1)[1]
        video_list = context.user_data.get('video_list', [])
        fmt = next((f for f in video_list if str(f['format_id']) == fmt_id), None)
        if not fmt:
            await query.message.reply_text("❌ Selected format not found.")
            return
        ext = fmt.get('ext', 'mp4')
        # Notify user
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
    elif data.startswith("audio_"):
        fmt_id = data.split("_", 1)[1]
        fmt = context.user_data.get('audio_format')
        if not fmt or str(fmt.get('format_id')) != fmt_id:
            await query.message.reply_text("❌ Selected audio format not found.")
            return
        ext = fmt.get('ext', 'm4a')
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_AUDIO)
    else:
        await query.message.reply_text("❌ Invalid selection.")
        return

    # Perform download in background thread to avoid blocking
    try:
        loop = asyncio.get_running_loop()
        file_path = await loop.run_in_executor(None, download_media, url, fmt_id, ext, config.DOWNLOAD_PATH)
    except Exception as e:
        await query.message.reply_text(f"❌ Download failed: {e}")
        return

    # Send the file or link based on size
    file_size = os.path.getsize(file_path)
    if file_size <= 50 * 1024 * 1024:
        # Small file: send directly
        if data.startswith("video_"):
            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
            with open(file_path, 'rb') as video_file:
                await context.bot.send_video(chat_id, video_file, caption="🎬 Here is your video!")
        else:
            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_AUDIO)
            with open(file_path, 'rb') as audio_file:
                await context.bot.send_audio(chat_id, audio_file, caption="🔊 Here is your audio!")
    else:
        # Large file: provide HTTP link
        filename = os.path.basename(file_path)
        link = f"http://{config.EXTERNAL_IP}:{config.HTTP_PORT}/{filename}"
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        await context.bot.send_message(chat_id, f"📁 File is large. Download here: {link}")

    # Clear user data to avoid conflicts
    context.user_data.clear()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle unexpected errors by notifying the user.
    """
    # Log the error
    print(f"Error: {context.error}")
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text("⚠️ An unexpected error occurred. Please try again later.")

def main():
    # Start HTTP server for large file downloads
    start_http_server(config.DOWNLOAD_PATH, config.HTTP_PORT)
    # Initialize the bot application
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_error_handler(error_handler)
    print("Bot started. Waiting for messages...")
    app.run_polling()

if __name__ == "__main__":
    main()

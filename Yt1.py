import os
import re
import shutil
import telebot
import yt_dlp

from telethon.sync import TelegramClient

# === Your Credentials ===
API_ID = 22815674
API_HASH = '3aa83fb0fe83164b9fee00a1d0b31e5f'
BOT_TOKEN = '7952616197:AAGQ8kJBVUcL17cUHs8bXLbPGTe9WRxhe20'
TARGET_CHANNEL = '@ALLVid_Download'

# === Initialize Bots ===
bot = telebot.TeleBot(BOT_TOKEN)
telethon_client = TelegramClient('session', API_ID, API_HASH)
telethon_client.start(bot_token=BOT_TOKEN)

# === Check ffmpeg availability ===
FFMPEG = shutil.which("ffmpeg") or ""

# === URL Extractor ===
def extract_url(text):
    url_regex = r'(https?://\S+)'
    match = re.search(url_regex, text)
    return match.group(1) if match else None

# === Progress Bar Hook ===
def video_progress_hook(chat_id, msg_id):
    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            if total:
                pct = downloaded * 100 / total
                bar_length = 12
                filled = int(bar_length * pct // 100)
                bar = '█' * filled + '░' * (bar_length - filled)
                text = (f"⬇️ Downloading...\n"
                        f"[{bar}] {pct:.1f}%\n"
                        f"{downloaded/1024/1024:.1f} MB of {total/1024/1024:.1f} MB")
                try:
                    bot.edit_message_text(text, chat_id, msg_id)
                except Exception:
                    pass
        elif d['status'] == 'finished':
            try:
                bot.edit_message_text("✅ Download complete! Preparing to send... 📦", chat_id, msg_id)
            except Exception:
                pass
    return hook

# === Main Handler ===
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    chat_id = message.chat.id
    url = extract_url(message.text or "")

    if not url:
        return bot.send_message(chat_id, "❌ Oops! Please send a valid URL 😅")

    # Notify User
    status = bot.send_message(chat_id, "⏳ Please wait while we prepare your video...")

    # yt-dlp Options
    if FFMPEG:
        format_choice = "bestvideo+bestaudio/best"
        merge_option = {'merge_output_format': 'mp4'}
    else:
        format_choice = "best"
        merge_option = {}

    ydl_opts = {
        'format': format_choice,
        'outtmpl': '%(title)s.%(ext)s',
        'progress_hooks': [video_progress_hook(chat_id, status.message_id)],
        **merge_option,
        'ffmpeg_location': FFMPEG,
        'noplaylist': True,
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if merge_option and not filename.endswith(".mp4"):
                filename = os.path.splitext(filename)[0] + ".mp4"
    except Exception as e:
        bot.edit_message_text(f"⚠️ Download failed:\n`{e}`", chat_id, status.message_id, parse_mode='Markdown')
        return

    # Send Video or Upload to Channel
    try:
        size = os.path.getsize(filename)
        caption = f"🎥 *{info.get('title', 'Video')}*"

        if size <= 50 * 1024 * 1024:
            with open(filename, 'rb') as vid:
                bot.send_video(chat_id, vid, caption=caption, parse_mode='Markdown')
        else:
            # Upload to channel
            try:
                bot.edit_message_text("⬆️ Uploading large file to channel...", chat_id, status.message_id)
            except:
                pass
            sent_msg = telethon_client.send_file(
                TARGET_CHANNEL, filename,
                caption=caption, parse_mode='md'
            )
            channel_link = f"https://t.me/{TARGET_CHANNEL.replace('@', '')}/{sent_msg.id}"
            bot.send_message(chat_id, f"✅ Your video is uploaded! 🎉\nGrab it here: {channel_link}")

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Sending failed:\n`{e}`", parse_mode='Markdown')
    finally:
        if os.path.exists(filename):
            os.remove(filename)

# === Start Bot ===
print("✅ Bot is running! Waiting for users...")
bot.infinity_polling()

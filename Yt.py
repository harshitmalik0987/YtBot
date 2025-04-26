import os
import re
import shutil
import telebot
import yt_dlp

# === Your Bot Token ===
TOKEN = "7952616197:AAGQ8kJBVUcL17cUHs8bXLbPGTe9WRxhe20"  # Replace with your bot token
bot = telebot.TeleBot(TOKEN)

# === Check if ffmpeg is installed ===
FFMPEG = shutil.which("ffmpeg") or ""

# === Extract URL from message ===
def extract_url(text):
    url_regex = r'(https?://\S+)'
    match = re.search(url_regex, text)
    return match.group(1) if match else None

# === Progress bar during download ===
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
                except:
                    pass
        elif d['status'] == 'finished':
            try:
                bot.edit_message_text("✅ Download complete! Preparing to send...", chat_id, msg_id)
            except:
                pass
    return hook

# === Main handler ===
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    chat_id = message.chat.id
    url = extract_url(message.text or "")

    if not url:
        return bot.send_message(chat_id, "❌ Please send a valid URL.")

    # Notify user
    status = bot.send_message(chat_id, "⏳ Starting download...")

    # Setup yt-dlp options
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

    # Send video or document
    try:
        size = os.path.getsize(filename)
        caption = f"🎥 *{info.get('title', 'Video')}*"

        if size <= 50 * 1024 * 1024:
            with open(filename, 'rb') as vid:
                bot.send_video(chat_id, vid, caption=caption, parse_mode='Markdown')
        else:
            with open(filename, 'rb') as doc:
                bot.send_document(chat_id, doc, caption=caption, parse_mode='Markdown')

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Sending file failed:\n`{e}`", parse_mode='Markdown')
    finally:
        if os.path.exists(filename):
            os.remove(filename)

# === Start polling ===
bot.infinity_polling()

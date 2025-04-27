# === Imports and Setup ===
import os
import re
import shutil
import asyncio
import telebot
from telebot import types
import yt_dlp
from telethon import TelegramClient

# --- Your Credentials ---
API_ID = 22815674
API_HASH = '3aa83fb0fe83164b9fee00a1d0b31e5f'
BOT_TOKEN = '7952616197:AAGQ8kJBVUcL17cUHs8bXLbPGTe9WRxhe20'
TARGET_CHANNEL = '@ALLVid_Download'  # Channel where large files will be uploaded

# --- Initialize AsyncIO Loop and Clients ---
# Create and set a new asyncio event loop for Telethon
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# Initialize Telethon client for file uploads
telethon_client = TelegramClient('session', API_ID, API_HASH)
telethon_client.start(bot_token=BOT_TOKEN)

# Initialize TeleBot for user interaction (disable threading to avoid event loop issues)
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# Check ffmpeg availability for merging formats
FFMPEG = shutil.which("ffmpeg") or ""

# Mapping from Telegram message IDs to user-requested URLs
user_requests = {}

# === Utility Functions ===

def extract_url(text):
    """
    Extract the first URL from a given text.
    Returns the URL string or None if not found.
    """
    url_regex = r'(https?://\S+)'
    match = re.search(url_regex, text)
    return match.group(1) if match else None

def video_progress_hook(chat_id, msg_id):
    """
    Create a progress hook function for yt-dlp.
    This function updates the Telegram message with download progress.
    """
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
            # Download finished
            try:
                bot.edit_message_text("✅ Download complete! Preparing to send... 📦", chat_id, msg_id)
            except Exception:
                pass
    return hook

def get_top_formats(info, top_n=3):
    """
    Determine the top N video formats from yt-dlp info dict.
    Returns a list of format dicts sorted by quality (resolution).
    """
    formats = info.get('formats', [])
    # Filter out formats without video or audio as needed
    if FFMPEG:
        # Prioritize video streams (to merge with audio)
        video_formats = [f for f in formats if f.get('vcodec') != 'none']
    else:
        # Only combined streams (video + audio)
        video_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
    # Filter out entries lacking height information
    video_formats = [f for f in video_formats if f.get('height') is not None]
    # Sort by resolution (height) descending
    video_formats.sort(key=lambda f: f['height'], reverse=True)
    # Pick top N unique heights
    seen = set()
    top_formats = []
    for fmt in video_formats:
        height = fmt['height']
        if height in seen:
            continue
        seen.add(height)
        top_formats.append(fmt)
        if len(top_formats) >= top_n:
            break
    return top_formats

# === Bot Handlers ===

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    """
    Handler for incoming text messages containing a URL.
    Extracts URL, retrieves video info, and presents format options via inline buttons.
    """
    chat_id = message.chat.id
    url = extract_url(message.text or "")
    if not url:
        bot.send_message(chat_id, "❌ Oops! Please send a valid URL.")
        return

    # Inform user we're processing
    bot.send_chat_action(chat_id, 'typing')
    status_msg = bot.send_message(chat_id, "⏳ Gathering video info, please wait...")

    # Extract video information without downloading
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'skip_download': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        bot.edit_message_text(f"⚠️ Failed to retrieve info:\n`{e}`",
                              chat_id, status_msg.message_id, parse_mode='Markdown')
        return

    # Get top 3 formats for user selection
    top_formats = get_top_formats(info, top_n=3)
    if not top_formats:
        bot.edit_message_text("⚠️ No suitable video formats found.",
                              chat_id, status_msg.message_id)
        return

    # Build inline keyboard with format choices
    markup = types.InlineKeyboardMarkup()
    buttons = []
    for fmt in top_formats:
        label = f"{fmt['height']}p ({fmt.get('ext','')})"
        callback_data = f"video_{fmt['format_id']}"
        buttons.append(types.InlineKeyboardButton(label, callback_data=callback_data))
    markup.add(*buttons)
    # Add an audio-only option
    audio_btn = types.InlineKeyboardButton("🔊 Audio Only", callback_data="audio_only")
    markup.add(audio_btn)

    # Save this request's URL associated with the message ID
    user_requests[status_msg.message_id] = url

    # Edit the status message to show format options
    bot.edit_message_text("Select a format to download:",
                          chat_id, status_msg.message_id,
                          reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """
    Handler for inline button callbacks (format selection).
    Downloads and sends the requested video or audio format.
    """
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data

    # Acknowledge callback
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    # Retrieve the original URL for this request
    url = user_requests.pop(msg_id, None)
    if not url:
        bot.send_message(chat_id,
                         "⚠️ Error: unable to retrieve video information. Please try again.")
        return

    # Determine if audio-only was requested
    is_audio = (data == "audio_only")
    if is_audio:
        format_choice = "bestaudio"
    elif data.startswith("video_"):
        fmt_id = data.split("_", 1)[1]
        if FFMPEG:
            # Merge chosen video with best audio
            format_choice = f"{fmt_id}+bestaudio"
        else:
            format_choice = fmt_id
    else:
        bot.send_message(chat_id, "⚠️ Unknown selection, please try again.")
        return

    # Inform user of download start
    bot.send_chat_action(chat_id, 'typing')
    status_msg = bot.send_message(chat_id, "⬇️ Downloading, please wait...")
    hook = video_progress_hook(chat_id, status_msg.message_id)

    # Set up yt-dlp download options
    ydl_opts = {
        'format': format_choice,
        'outtmpl': '%(title)s.%(ext)s',
        'progress_hooks': [hook],
        'quiet': True,
        'noplaylist': True,
    }
    if FFMPEG and not is_audio:
        ydl_opts['merge_output_format'] = 'mp4'
        ydl_opts['ffmpeg_location'] = FFMPEG
    if is_audio and FFMPEG:
        ydl_opts['ffmpeg_location'] = FFMPEG
        # Convert audio to mp3 for compatibility
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    # Perform the download
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not is_audio and FFMPEG and not filename.endswith(".mp4"):
                filename = os.path.splitext(filename)[0] + ".mp4"
    except Exception as e:
        bot.edit_message_text(f"⚠️ Download failed:\n`{e}`",
                              chat_id, status_msg.message_id,
                              parse_mode='Markdown')
        return

    # Prepare caption and title
    title = info.get('title', 'Media')
    caption = f"*{title}*"
    if is_audio:
        caption = f"🔊 {caption}"

    try:
        size = os.path.getsize(filename)
        if size <= 50 * 1024 * 1024:
            # Send directly if under 50MB
            if is_audio:
                bot.send_chat_action(chat_id, 'upload_audio')
                with open(filename, 'rb') as f:
                    bot.send_audio(chat_id, f, caption=caption, parse_mode='Markdown')
            else:
                bot.send_chat_action(chat_id, 'upload_video')
                with open(filename, 'rb') as f:
                    bot.send_video(chat_id, f, caption=caption, parse_mode='Markdown')
            bot.edit_message_text("✅ Download and upload complete!",
                                  chat_id, status_msg.message_id)
        else:
            # For large files, upload to channel via Telethon
            bot.send_chat_action(chat_id, 'upload_document')
            bot.edit_message_text("⬆️ Uploading large file to channel...",
                                  chat_id, status_msg.message_id)

            # Properly await Telethon send_file
            sent_msg = loop.run_until_complete(
                telethon_client.send_file(
                    TARGET_CHANNEL,
                    filename,
                    caption=caption,
                    parse_mode='md'
                )
            )
            channel_link = f"https://t.me/{TARGET_CHANNEL.strip('@')}/{sent_msg.id}"
            bot.send_message(chat_id,
                             f"✅ Your file is ready! 🎉\nGrab it here: {channel_link}")
            bot.edit_message_text("✅ Upload complete!",
                                  chat_id, status_msg.message_id)
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Sending failed:\n`{e}`", parse_mode='Markdown')
    finally:
        # Cleanup the downloaded file
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

# === Start Bot ===
print("✅ Bot is running! Waiting for users...")
bot.infinity_polling()

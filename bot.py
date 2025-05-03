import sys, types
import os
import logging
import re
import html
import time
import json
import threading
from datetime import datetime, timedelta
from io import BufferedReader, FileIO
from collections import defaultdict, deque

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction, InputMediaPhoto
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext
import yt_dlp
from google.cloud import storage

# Patch imghdr if missing
try:
    import imghdr
except ModuleNotFoundError:
    imghdr = types.ModuleType('imghdr')
    imghdr.what = lambda *args, **kwargs: None
    sys.modules['imghdr'] = imghdr

# ─── Configuration ───
TELEGRAM_TOKEN = '7952616197:AAHaUzEt37uL44CUC9RsJwbZs1TAqnL4CRo'
STORAGE_BUCKET = 'ankushmalikbot'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_JSON = os.path.join(BASE_DIR, 'healthy-hearth-458109-u8-34db6329b953.json')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = SERVICE_JSON

storage_client = storage.Client.from_service_account_json(SERVICE_JSON)
bucket = storage_client.bucket(STORAGE_BUCKET)

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DAILY_USER_LIMIT = 2 * 1024 * 1024 * 1024  # 2GB
USAGE_FILE = os.path.join(BASE_DIR, 'user_usage.json')

def load_usage():
    try:
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_usage(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f)

def get_user_usage(user_id):
    usage = load_usage()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    entry = usage.get(str(user_id), {"date": today, "used": 0})
    if entry.get("date") != today:
        entry = {"date": today, "used": 0}
    return entry["used"]

def add_usage(user_id, size):
    usage = load_usage()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if str(user_id) not in usage or usage[str(user_id)].get("date") != today:
        usage[str(user_id)] = {"date": today, "used": 0}
    usage[str(user_id)]["used"] += size
    save_usage(usage)

# --- ProgressFile for Upload ---
class ProgressFile(BufferedReader):
    def __init__(self, filename, callback):
        f = FileIO(filename, 'rb')
        super().__init__(raw=f)
        self._callback = callback
        self.length = os.stat(filename).st_size

    def read(self, size=-1):
        data = super().read(size)
        if not data:
            return data
        self._callback(self.tell(), self.length)
        return data

# --- Queues ---
user_queues = defaultdict(deque)
user_locks = defaultdict(threading.Lock)

def process_next_in_queue(user_id, context):
    if user_queues[user_id]:
        job = user_queues[user_id].popleft()
        threading.Thread(target=job, daemon=True).start()
    else:
        with user_locks[user_id]:
            pass

# --- Bot Handlers ---
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "<b>Welcome!</b> 👋\nSend a YouTube, Twitter, Instagram, or any video link and I'll help you download it!\n"
        "<b>Note:</b> Admin of Bot @ankush_malik Contact for Remove Limit\n"
        "Type /help for more info.",
        parse_mode='HTML'
    )

def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "<b>How to use:</b>\n"
        "1. Send a video/audio link (YouTube, Twitter, Instagram, etc).\n"
        "2. Choose your desired format.\n"
        "3. The file will be sent directly, or a download link will be provided if too large.\n\n"
        "<b>Limits:</b>\n"
        "• 2GB download limit per user per day.\n"
        "•Contact @ankush_malik for Remove Limit and other Support\n"
        "• /usage — See your daily download usage.",
        parse_mode='HTML'
    )

def usage_cmd(update: Update, context: CallbackContext):
    used = get_user_usage(update.effective_user.id)
    rem = DAILY_USER_LIMIT - used
    update.message.reply_text(
        f"📊 <b>Your Usage Today</b>:\n"
        f"Downloaded: <b>{used // (1024*1024)} MB</b>\n"
        f"Remaining: <b>{rem // (1024*1024)} MB</b>\n"
        f"Limit: <b>{DAILY_USER_LIMIT // (1024*1024*1024)} GB</b>",
        parse_mode='HTML'
    )

def is_supported_url(url):
    return re.match(
        r"https?://(?:www\.)?(youtube\.com|youtu\.be|twitter\.com|instagram\.com|facebook\.com|fb\.watch)/", url
    )

def handle_link(update: Update, context: CallbackContext):
    text = update.message.text or ""
    match = re.search(r'https?://\S+', text)
    if not match:
        return update.message.reply_text("⚠️ Please send a valid video/audio URL.")
    url = match.group(0)
    if not is_supported_url(url):
        return update.message.reply_text("⚠️ Only YouTube, Twitter, Instagram, or Facebook video/audio URLs are supported.")

    user_id = update.effective_user.id
    used = get_user_usage(user_id)
    if used >= DAILY_USER_LIMIT:
        return update.message.reply_text("🚫 You have reached your 2GB daily download limit. Try again tomorrow.")

    update.message.reply_chat_action(ChatAction.TYPING)
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'cookiefile': os.path.join(BASE_DIR, "cookies.txt")}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        err = html.escape(str(e))
        return update.message.reply_text(
            f"❌ <b>Failed to fetch formats:</b>\n<code>{err}</code>",
            parse_mode='HTML'
        )

    context.user_data['yt_info'] = info
    formats = info.get('formats', [])
    video_formats = [f for f in formats if f.get('vcodec') != 'none']
    audio_formats = [f for f in formats if f.get('vcodec') == 'none']

    buttons = []
    # Add all video+audio formats (progressive = has both)
    progressive = [f for f in video_formats if f.get('acodec') != 'none']
    if progressive:
        for v in sorted(progressive, key=lambda f: (f.get('height') or 0), reverse=True):
            fid = v.get('format_id')
            ext = v.get('ext')
            res = v.get('height', 'Unknown')
            size = v.get('filesize') or 0
            size_text = f"{size//(1024*1024)}MB" if size else ''
            buttons.append([InlineKeyboardButton(f"📹 {res}p ({ext}) {size_text}", callback_data=f"vid_{fid}")])

    # Add all video-only formats (to be merged with best audio)
    for v in sorted([f for f in video_formats if f.get('acodec') == 'none'], key=lambda f: (f.get('height') or 0), reverse=True):
        fid = v.get('format_id')
        ext = v.get('ext')
        res = v.get('height', 'Unknown')
        size = v.get('filesize') or 0
        size_text = f"{size//(1024*1024)}MB" if size else ''
        buttons.append([InlineKeyboardButton(f"🎬 {res}p (No audio, {ext}) {size_text}", callback_data=f"vid_{fid}")])

    # Add all audio-only formats
    for a in sorted(audio_formats, key=lambda f: (f.get('abr') or 0), reverse=True):
        fid = a.get('format_id')
        ext = a.get('ext')
        abr = a.get('abr', 'Unknown')
        size = a.get('filesize') or 0
        size_text = f"{size//(1024*1024)}MB" if size else ''
        buttons.append([InlineKeyboardButton(f"🎵 {abr}kbps {ext} {size_text}", callback_data=f"aud_{fid}")])

    # Option: Extract audio as mp3
    buttons.append([InlineKeyboardButton("🎧 Extract audio only (mp3)", callback_data="audio_mp3")])

    title = html.escape(info.get('title', 'media'))
    thumb_url = info.get('thumbnail')

    # Send thumbnail as photo with caption, then format selection as reply
    if thumb_url:
        update.message.reply_photo(photo=thumb_url, caption=f"<b>{title}</b>", parse_mode='HTML')

    update.message.reply_text(
        f"📥 <b>Choose a format for:</b> <i>{title}</i>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='HTML'
    )

def handle_format_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    def job():
        try:
            _handle_format_selection_threadsafe(update, context)
        finally:
            process_next_in_queue(user_id, context)

    with user_locks[user_id]:
        if user_queues[user_id]:
            query.answer("Another download is in progress for you. Your request is queued.", show_alert=True)
            user_queues[user_id].append(lambda: job())
        else:
            user_queues[user_id].append(lambda: job())
            process_next_in_queue(user_id, context)

def _handle_format_selection_threadsafe(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    info = context.user_data.get('yt_info')
    user_id = query.from_user.id

    if not info:
        return query.edit_message_text("⚠️ Session expired. Please send the link again.")

    url = info.get('webpage_url') or info.get('url')
    title = html.escape(info.get('title', 'media'))
    base_out = os.path.join(BASE_DIR, f"{info.get('id')}_{data}")
    out_template = base_out + ".%(ext)s"

    def download_progress(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            pct = downloaded * 100 / total if total else 0
            text = f"⬇️ Downloading {pct:.0f}% ({downloaded//(1024*1024)}MB/{total//(1024*1024)}MB)"
            try:
                context.bot.edit_message_text(text, query.message.chat_id, query.message.message_id)
            except Exception:
                pass
        elif d['status'] == 'finished':
            try:
                context.bot.edit_message_text("⬇️ Download complete.", query.message.chat_id, query.message.message_id)
            except Exception:
                pass

    # --- Improved: Always merge video+audio ---
    if data == "audio_mp3":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "cookiefile": os.path.join(BASE_DIR, "cookies.txt"),
            "progress_hooks": [download_progress],
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        }
    elif data.startswith("vid_"):
        fmt_id = data.split("_", 1)[1]
        # Use bestaudio+format_id to merge video+audio if needed
        ydl_opts = {
            "format": f"{fmt_id}+bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "cookiefile": os.path.join(BASE_DIR, "cookies.txt"),
            "progress_hooks": [download_progress],
            "merge_output_format": "mp4",  # Ensure output is mp4 after merging
        }
    elif data.startswith("aud_"):
        fmt_id = data.split("_", 1)[1]
        ydl_opts = {
            "format": fmt_id,
            "outtmpl": out_template,
            "quiet": True,
            "cookiefile": os.path.join(BASE_DIR, "cookies.txt"),
            "progress_hooks": [download_progress],
        }
    else:
        return query.edit_message_text("❌ Unknown format selected.")

    msg = query.edit_message_text(f"⬇️ Downloading <b>{title}</b>...", parse_mode='HTML')
    chat_id = msg.chat_id
    msg_id = msg.message_id

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        err = html.escape(str(e))
        return context.bot.send_message(
            chat_id,
            f"❌ <b>Download Error:</b>\n<code>{err}</code>",
            parse_mode='HTML'
        )

    files = [f for f in os.listdir(BASE_DIR) if f.startswith(f"{info.get('id')}_{data}")]
    if not files:
        return context.bot.send_message(chat_id, "⚠️ Cannot find the downloaded file.")
    filepath = os.path.join(BASE_DIR, files[0])
    size = os.path.getsize(filepath)

    used = get_user_usage(user_id)
    if used + size > DAILY_USER_LIMIT:
        os.remove(filepath)
        return context.bot.send_message(chat_id, "🚫 This download would exceed your 2GB daily limit. Try a smaller file or wait until tomorrow.")

    add_usage(user_id, size)

    if size <= 50 * 1024 * 1024:
        try:
            context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
            with open(filepath, 'rb') as f:
                context.bot.send_document(chat_id, f)
        except Exception as e:
            logger.warning("Direct send failed, uploading to cloud: %s", e)
            _upload_to_bucket(context, chat_id, filepath)
    else:
        _upload_to_bucket(context, chat_id, filepath)

    if os.path.exists(filepath):
        os.remove(filepath)

def _upload_to_bucket(context: CallbackContext, chat_id, filepath):
    wait_msg = context.bot.send_message(chat_id, "☁️ Uploading to cloud, please wait…")
    wait_id = wait_msg.message_id

    blob = bucket.blob(os.path.basename(filepath))
    blob.chunk_size = 2 * 1024 * 1024

    # --- Set auto-delete after 24h (GCS "temporary hold" is not for this, use lifecycle or set custom time-based deletion) ---
    expires_at = datetime.utcnow() + timedelta(hours=24)
    blob.metadata = {'delete_at': expires_at.isoformat()}
    pf = ProgressFile(filepath, lambda pos, total: _upload_progress(context, chat_id, wait_id, pos, total))
    try:
        blob.upload_from_file(pf, timeout=900)
        # Set GCS lifecycle rule to auto-delete (recommended, see below)
        public_url = f"https://storage.googleapis.com/{STORAGE_BUCKET}/{os.path.basename(filepath)}"
        context.bot.edit_message_text(
            f"☁️ Upload complete!\n🔗 <b>Download link (valid for 24h):</b>\n{public_url}",
            chat_id, wait_id,
            parse_mode='HTML'
        )
    except Exception as e:
        err = html.escape(str(e))
        logger.error("Upload error: %s", e, exc_info=True)
        try:
            context.bot.edit_message_text(
                f"❌ <b>Upload Error:</b>\n<code>{err}</code>",
                chat_id, wait_id,
                parse_mode='HTML'
            )
        except Exception:
            context.bot.send_message(chat_id, f"❌ Upload failed: {err}")
    finally:
        pf.close()
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass

def _upload_progress(context, chat_id, wait_id, position, total):
    now = time.time()
    if not hasattr(_upload_progress, 'last_update'):
        _upload_progress.last_update = 0
    if (now - _upload_progress.last_update) >= 1 or position == total:
        percent = position * 100 / total if total else 0
        text = f"☁️ Uploading... {percent:.0f}%"
        try:
            context.bot.edit_message_text(text, chat_id, wait_id)
        except Exception:
            pass
        _upload_progress.last_update = now

# --- GCS Lifecycle Management (recommended, set once!) ---
# In Google Cloud Console: Storage > your-bucket > "Lifecycle" > Add Rule: "Age" = 1 Day, "Delete"
# Or via code:
# from google.cloud import storage
# def set_lifecycle(bucket):
#     rule = {"action": {"type": "Delete"}, "condition": {"age": 1}}
#     bucket.add_lifecycle_delete_rule(age=1)
#     bucket.patch()
# set_lifecycle(bucket)
# Only needs to be run once, not in the main bot loop.

def error_handler(update, context):
    logger.error("Exception while handling update:", exc_info=context.error)

def main():
    updater = Updater(
        TELEGRAM_TOKEN,
        use_context=True,
        request_kwargs={'read_timeout': 300, 'connect_timeout': 300}
    )
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("usage", usage_cmd))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_link))
    dp.add_handler(CallbackQueryHandler(handle_format_selection))
    dp.add_error_handler(error_handler)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

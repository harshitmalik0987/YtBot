import sys, types
# Patch imghdr if missing (for environments without PIL, etc.)
try:
    import imghdr
except ModuleNotFoundError:
    imghdr = types.ModuleType('imghdr')
    imghdr.what = lambda *args, **kwargs: None
    sys.modules['imghdr'] = imghdr

import os
import logging
import re
import html
import time
from io import BufferedReader, FileIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext
import yt_dlp
from google.cloud import storage

# ─── Configuration ────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = '7952616197:AAHaUzEt37uL44CUC9RsJwbZs1TAqnL4CRo'
STORAGE_BUCKET = 'ankushmalikbot'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_JSON = os.path.join(BASE_DIR, 'healthy-hearth-458109-u8-3427749c236e.json')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = SERVICE_JSON

# Initialize Google Cloud Storage client
storage_client = storage.Client.from_service_account_json(SERVICE_JSON)
bucket = storage_client.bucket(STORAGE_BUCKET)

# Logging configuration
logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── ProgressFile Wrapper for Upload ──────────────────────────────────────────

class ProgressFile(BufferedReader):
    """
    Wraps a file object and calls a callback with upload progress.
    """
    def __init__(self, filename, callback):
        f = FileIO(file=filename, mode='r')
        super().__init__(raw=f)
        self._callback = callback
        self.length = os.stat(filename).st_size

    def read(self, size=-1):
        data = super().read(size)
        if not data:
            return data
        # Invoke callback with (bytes_read, total_bytes)
        self._callback(self.tell(), self.length)
        return data

# ─── Telegram Bot Handlers ────────────────────────────────────────────────────

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "<b>Welcome!</b> 👋\nSend a YouTube, Twitter, Instagram, or any video link and I'll help you download it!",
        parse_mode='HTML'
    )

def handle_link(update: Update, context: CallbackContext):
    text = update.message.text or ""
    match = re.search(r'https?://\S+', text)
    if not match:
        return update.message.reply_text("⚠️ Please send a valid URL.")

    url = match.group(0)
    update.message.reply_chat_action(ChatAction.TYPING)
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        err = html.escape(str(e))
        return update.message.reply_text(
            f"❌ <b>Failed to fetch formats:</b>\n<code>{err}</code>",
            parse_mode='HTML'
        )

    context.user_data['yt_info'] = info
    formats = info.get('formats', [])
    vids = [f for f in formats if f.get('vcodec') != 'none']
    auds = [f for f in formats if f.get('vcodec') == 'none']

    if not vids and not auds:
        return update.message.reply_text("⚠️ No downloadable formats found.")

    # Offer up to 3 highest-quality video formats and the best audio format
    vids = sorted(vids, key=lambda f: f.get('height') or 0, reverse=True)[:3]
    best_audio = max(auds, key=lambda f: f.get('abr') or 0) if auds else None

    buttons = []
    for v in vids:
        fid = v.get('format_id')
        ext = v.get('ext')
        res = v.get('height', 'Unknown')
        size = v.get('filesize') or 0
        size_text = f"{size//(1024*1024)}MB" if size else ''
        buttons.append([InlineKeyboardButton(f"📹 {res}p {ext} {size_text}", callback_data=fid)])
    if best_audio:
        fid = best_audio.get('format_id')
        ext = best_audio.get('ext')
        abr = best_audio.get('abr', 'Unknown')
        size = best_audio.get('filesize') or 0
        size_text = f"{size//(1024*1024)}MB" if size else ''
        buttons.append([InlineKeyboardButton(f"🎵 {abr}kbps {ext} {size_text}", callback_data=fid)])

    title = html.escape(info.get('title', 'media'))
    update.message.reply_text(
        f"📥 <b>Choose a format for:</b> <i>{title}</i>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='HTML'
    )

def handle_format_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    fmt_id = query.data
    info = context.user_data.get('yt_info')

    if not info:
        return query.edit_message_text("⚠️ Session expired. Please send the link again.")

    url = info.get('webpage_url') or info.get('url')
    title = html.escape(info.get('title', 'media'))
    out_template = os.path.join(BASE_DIR, f"{info.get('id')}_{fmt_id}.%(ext)s")

    # Notify user of download start
    msg = query.edit_message_text(f"⬇️ Downloading <b>{title}</b>...", parse_mode='HTML')
    chat_id = msg.chat_id
    msg_id = msg.message_id

    # Callback for download progress
    def download_progress(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            pct = downloaded * 100 / total if total else 0
            text = f"⬇️ Downloading {pct:.0f}% ({downloaded//(1024*1024)}MB/{total//(1024*1024)}MB)"
            try:
                context.bot.edit_message_text(text, chat_id, msg_id)
            except Exception:
                pass
        elif d['status'] == 'finished':
            try:
                context.bot.edit_message_text("⬇️ Download complete.", chat_id, msg_id)
            except Exception:
                pass

    try:
        with yt_dlp.YoutubeDL({
            'format': fmt_id,
            'outtmpl': out_template,
            'quiet': True,
            'progress_hooks': [download_progress]
        }) as ydl:
            ydl.download([url])
    except Exception as e:
        err = html.escape(str(e))
        return context.bot.send_message(
            chat_id,
            f"❌ <b>Download Error:</b>\n<code>{err}</code>",
            parse_mode='HTML'
        )

    # Locate the downloaded file
    base = f"{info.get('id')}_{fmt_id}"
    files = [f for f in os.listdir(BASE_DIR) if f.startswith(base)]
    if not files:
        return context.bot.send_message(chat_id, "⚠️ Cannot find the downloaded file.")
    filepath = os.path.join(BASE_DIR, files[0])
    size = os.path.getsize(filepath)

    # If small file, send directly; else upload to cloud
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

    # Cleanup: delete local file if it still exists
    if os.path.exists(filepath):
        os.remove(filepath)

def _upload_to_bucket(context: CallbackContext, chat_id, filepath):
    """
    Upload a file to Google Cloud Storage with progress updates.
    """
    wait_msg = context.bot.send_message(chat_id, "☁️ Uploading to cloud, please wait…")
    wait_id = wait_msg.message_id

    blob = bucket.blob(os.path.basename(filepath))
    blob.chunk_size = 2 * 1024 * 1024  # 2MB chunks for progress updates

    # Callback for upload progress
    def upload_progress(position, total):
        now = time.time()
        if not hasattr(upload_progress, 'last_update'):
            upload_progress.last_update = 0
        # Update at most once per second or on completion
        if (now - upload_progress.last_update) >= 1 or position == total:
            percent = position * 100 / total if total else 0
            text = f"☁️ Uploading... {percent:.0f}%"
            try:
                context.bot.edit_message_text(text, chat_id, wait_id)
            except Exception:
                pass
            upload_progress.last_update = now

    pf = ProgressFile(filepath, upload_progress)
    try:
        # Perform the upload (with a 15-minute timeout)
        blob.upload_from_file(pf, timeout=900)
        public_url = f"https://storage.googleapis.com/{STORAGE_BUCKET}/{os.path.basename(filepath)}"
        context.bot.edit_message_text(
            f"☁️ Upload complete!\n🔗 <b>Download link:</b>\n{public_url}",
            chat_id, wait_id,
            parse_mode='HTML'
        )
    except Exception as e:
        err = html.escape(str(e))
        logger.error("Upload error: %s", e, exc_info=True)
        # Notify user of upload error
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
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_link))
    dp.add_handler(CallbackQueryHandler(handle_format_selection))
    dp.add_error_handler(error_handler)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

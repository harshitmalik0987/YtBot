# ─── Workaround for missing imghdr on Pydroid3 ─────────────────────────────
import sys, types
try:
    import imghdr
except ModuleNotFoundError:
    imghdr = types.ModuleType('imghdr')
    imghdr.what = lambda *args, **kwargs: None
    sys.modules['imghdr'] = imghdr

# ─── Imports ───────────────────────────────────────────────────────────────
import logging, os, re, uuid, html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackQueryHandler, CallbackContext
)
import yt_dlp
from google.cloud import storage

# ─── Configuration ────────────────────────────────────────────────────────
TELEGRAM_TOKEN = '7952616197:AAGYkec2BuE3_xkoG2TtyqhR2L0aKutX91w'
STORAGE_BUCKET  = 'telegram-ytdl-bot'
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
SERVICE_JSON    = os.path.join(BASE_DIR, 'healthy-hearth-458109-u8-4b6147e5d59e.json')
if not os.path.isfile(SERVICE_JSON):
    raise FileNotFoundError(f"Service JSON not found at: {SERVICE_JSON}")
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = SERVICE_JSON

# Initialize GCS client & bucket
storage_client = storage.Client.from_service_account_json(SERVICE_JSON)
bucket = storage_client.bucket(STORAGE_BUCKET)

# ─── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Bot Handlers ──────────────────────────────────────────────────────────

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "<b>Hello!</b> 👋\nSend me a video/audio link and I'll list download formats.",
        parse_mode='HTML'
    )

def handle_link(update: Update, context: CallbackContext):
    text = update.message.text or ""
    m = re.search(r'https?://\S+', text)
    if not m:
        return update.message.reply_text("⚠️ Please send a valid URL.")
    url = m.group(0)

    update.message.reply_chat_action(ChatAction.TYPING)
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        err = html.escape(str(e))
        return update.message.reply_text(
            f"❌ <b>Error fetching formats:</b>\n<code>{err}</code>",
            parse_mode='HTML'
        )

    context.user_data['yt_info'] = info
    fmts = info.get('formats', [])
    vids = [f for f in fmts if f.get('vcodec')!='none' and f.get('acodec')!='none']
    auds = [f for f in fmts if f.get('vcodec')=='none']

    if not vids and not auds:
        return update.message.reply_text("⚠️ No downloadable formats found.")

    vids = sorted(vids, key=lambda f: f.get('height') or 0, reverse=True)[:3]
    best_audio = max(auds, key=lambda f: f.get('abr') or 0) if auds else None

    buttons = []
    for f in vids:
        fid = html.escape(f.get('format_id',''))
        ext = html.escape(f.get('ext',''))
        h   = f.get('height') or 0
        sz  = f.get('filesize') or 0
        szm = f"{sz//(1024*1024)}MB" if sz else ''
        buttons.append([InlineKeyboardButton(f"📹 {h}p {ext} {szm}", callback_data=fid)])
    if best_audio:
        fid = html.escape(best_audio.get('format_id',''))
        ext = html.escape(best_audio.get('ext',''))
        abr = best_audio.get('abr') or 0
        sz  = best_audio.get('filesize') or 0
        szm = f"{sz//(1024*1024)}MB" if sz else ''
        buttons.append([InlineKeyboardButton(f"🎵 {abr}kbps {ext} {szm}", callback_data=fid)])

    title = html.escape(info.get('title','media'))
    update.message.reply_text(
        f"📥 <b>Available formats for:</b> <i>{title}</i>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='HTML'
    )

def handle_format_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    fmt_id = query.data
    info   = context.user_data.get('yt_info')
    if not info:
        return query.edit_message_text("⚠️ Session expired; send the link again.")

    url   = info.get('webpage_url') or info.get('url')
    title = html.escape(info.get('title','media'))
    out   = os.path.join(BASE_DIR, f"{info.get('id')}_{fmt_id}.%(ext)s")

    # Send initial progress message
    msg = query.edit_message_text(f"⬇️ Starting download of <b>{title}</b>...", parse_mode='HTML')
    chat_id, msg_id = msg.chat_id, msg.message_id

    def prog(d):
        if d['status']=='downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            done  = d.get('downloaded_bytes',0)
            pct   = done*100/total if total else 0
            text  = f"⬇️ Downloading {pct:.0f}% ({done//(1024*1024)}MB/{total//(1024*1024)}MB)"
            try: context.bot.edit_message_text(text, chat_id, msg_id)
            except: pass
        elif d['status']=='finished':
            try: context.bot.edit_message_text("⬇️ Download complete.", chat_id, msg_id)
            except: pass

    try:
        with yt_dlp.YoutubeDL({
            'format': fmt_id,
            'outtmpl': out,
            'quiet': True,
            'progress_hooks': [prog]
        }) as ydl:
            ydl.download([url])
    except Exception as e:
        err = html.escape(str(e))
        return context.bot.send_message(
            chat_id,
            f"❌ <b>Download error:</b>\n<code>{err}</code>",
            parse_mode='HTML'
        )

    # Find the downloaded file
    base = f"{info.get('id')}_{fmt_id}"
    files = [f for f in os.listdir(BASE_DIR) if f.startswith(base)]
    if not files:
        return context.bot.send_message(chat_id, "⚠️ Can't locate the downloaded file.")
    filepath = os.path.join(BASE_DIR, files[0])
    size     = os.path.getsize(filepath)

    # Send directly if small, else upload to GCS
    if size <= 50*1024*1024:
        try:
            context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
            with open(filepath,'rb') as f:
                context.bot.send_document(chat_id, f)
        except Exception as ne:
            logger.warning("Direct send failed: %s", ne)
            # fallback to upload
            blob = bucket.blob(os.path.basename(filepath))
            blob.upload_from_filename(filepath)
            public_url = f"https://storage.googleapis.com/{STORAGE_BUCKET}/{os.path.basename(filepath)}"
            context.bot.send_message(chat_id, f"☁️ Fallback upload complete:\n{public_url}")
        finally:
            os.remove(filepath)
    else:
        blob = bucket.blob(os.path.basename(filepath))
        total = size
        up_msg = context.bot.send_message(chat_id, "☁️ Uploading 0% (0MB)…")
        up_id  = up_msg.message_id
        chunk  = 256*1024
        blob.chunk_size = chunk
        with open(filepath,'rb') as f, blob.open("wb") as g:
            done = 0
            while True:
                data = f.read(chunk)
                if not data: break
                g.write(data)
                done += len(data)
                pct = done*100/total
                text = f"☁️ Uploading {pct:.0f}% ({done//(1024*1024)}MB/{total//(1024*1024)}MB)"
                try: context.bot.edit_message_text(text, chat_id, up_id)
                except: pass

        public_url = f"https://storage.googleapis.com/{STORAGE_BUCKET}/{os.path.basename(filepath)}"
        context.bot.edit_message_text(
            f"☁️ Upload complete!\n🔗 Download link:\n{public_url}",
            chat_id, up_id
        )
        os.remove(filepath)

def error_handler(update, context):
    logger.error("Error in update:", exc_info=context.error)

# ─── Main ─────────────────────────────────────────────────────────────────

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
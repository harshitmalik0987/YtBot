import types, sys
imghdr = types.ModuleType("imghdr")
imghdr.what = lambda *a, **k: None
sys.modules["imghdr"] = imghdr

import logging
import os
import requests
import base64
import re
import datetime

from telegram import Update, ParseMode, ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Optional libs for docs
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
try:
    import docx  # python-docx
except ImportError:
    docx = None

# ─── Credentials ───────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8065502134:AAFKlUwlHs6W7nvIpaxpZNg_okFXdyUyPGU"
GEMINI_API_KEY = "AIzaSyCiO6InSNB6PpxNyAEdDuvQmW-baGFyX0U"
# ────────────────────────────────────────────────────────────────────────────────

# ─── Config ────────────────────────────────────────────────────────────────────
ADMIN_USERNAMES = {"ankush_malik", "quicksmmadmin"}  # lowercase
DAILY_TOKEN_LIMIT = 25000
# ────────────────────────────────────────────────────────────────────────────────

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Data Stores ────────────────────────────────────────────────────────────────
# chat_id → {"history": [...], "tokens_today": int, "last_date": date}
user_data = {}
# chat_id → username
all_users = {}
# ────────────────────────────────────────────────────────────────────────────────

def current_date():
    return datetime.datetime.now().date()

def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def ensure_user(chat_id, username):
    data = user_data.setdefault(chat_id, {
        "history": [], "tokens_today": 0, "last_date": current_date()
    })
    # reset daily if date changed
    if data["last_date"] != current_date():
        data["tokens_today"] = 0
        data["last_date"] = current_date()
    all_users[chat_id] = username or str(chat_id)
    return data

# ─── MarkdownV2 Escape ─────────────────────────────────────────────────────────
def escape_markdown_v2(text: str) -> str:
    code_blocks, inline_codes = [], []
    def rb(m):
        code_blocks.append(m.group(0)); return f"§CB{len(code_blocks)-1}§"
    text = re.sub(r"```[\s\S]*?```", rb, text)
    def ri(m):
        inline_codes.append(m.group(0)); return f"§IC{len(inline_codes)-1}§"
    text = re.sub(r"`[^`\n]+`", ri, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"_(.+?)_", r"_\1_", text)
    special = r"_*[]()~`>#+-=|{}.!|"
    out = []
    for ch in text:
        if ch in ("*", "_"):
            out.append(ch)
        elif ch in special:
            out.append("\\" + ch)
        else:
            out.append(ch)
    text = "".join(out)
    for i, code in enumerate(inline_codes):
        text = text.replace(f"§IC{i}§", code)
    for i, block in enumerate(code_blocks):
        text = text.replace(f"§CB{i}§", block)
    return text

# ─── Gemini API ────────────────────────────────────────────────────────────────
def call_gemini(contents):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    headers = {"Content-Type": "application/json"}
    body = {"contents": contents}
    try:
        r = requests.post(url, headers=headers, json=body, timeout=60)
        r.raise_for_status()
        resp = r.json()
        parts = resp["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
        tokens = resp.get("totalTokenCount", count_tokens(text))
        return text, None, tokens
    except Exception as e:
        return "", str(e), 0

# ─── Typing Indicator ──────────────────────────────────────────────────────────
def send_typing(update: Update, context: CallbackContext):
    context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

# ─── Personality Replies ──────────────────────────────────────────────────────
def personality(update: Update, context: CallbackContext) -> bool:
    txt = (update.message.text or "").lower()
    if "your name" in txt:
        update.message.reply_markdown_v2("*🤖 My name is VisionAI*")
        return True
    if "your model" in txt:
        update.message.reply_markdown_v2("*🔧 I run on VisionAI 1.5 Flash*")
        return True
    if "owner" in txt:
        update.message.reply_markdown_v2("*👤 My owner is @Ankush_Malik*")
        return True
    return False

# ─── Command Handlers ─────────────────────────────────────────────────────────
def start(update: Update, context: CallbackContext):
    send_typing(update, context)
    ensure_user(update.effective_chat.id, update.effective_user.username)
    msg = (
        "🚀 *Welcome to VisionAI!* 🚀\n\n"
        "✨ *Capabilities* ✨\n"
        "• Chat with Gemini AI\n"
        "• Analyze images with captions/questions\n"
        "• Summarize PDF/DOCX/TXT\n"
        "  (send 'full text' in caption for full extract)\n\n"
        "Type /help to see all commands!"
    )
    update.message.reply_markdown_v2(escape_markdown_v2(msg))

def help_cmd(update: Update, context: CallbackContext):
    send_typing(update, context)
    ensure_user(update.effective_chat.id, update.effective_user.username)

    # Plain-text help to avoid any MarkdownV2 parsing issues
    help_text = (
        "📖 VisionAI Help 📖\n\n"
        "🛠 Commands:\n"
        "/start   – Launch bot\n"
        "/help    – This help menu\n"
        "/features– Bot capabilities\n"
        "/reset   – (admin only) Reset history & tokens\n"
        "/stats   – Token usage stats\n"
        "/user    – (admin only) List users\n\n"
        "👤 Admins: @Ankush_Malik\n"
        "🤖 Bot: VisionAI\n"
        "🔧 Model: VisionAI 1.5 Flash\n"
    )
    update.message.reply_text(help_text)

# … (rest of your handlers remain unchanged) …

def features(update: Update, context: CallbackContext):
    send_typing(update, context)
    ensure_user(update.effective_chat.id, update.effective_user.username)
    txt = (
        "✨ *Features* ✨\n"
        "• 💬 Chat with *VisionAI 1.5 Flash*\n"
        "• 📸 Image Q&A & captioning\n"
        "• 📄 Doc summarization (PDF/DOCX/TXT)\n"
        "• 📋 'Full text' option\n"
        "• 📊 Daily limit: 25,000 tokens\n"
        "• 🎨 Markdown: **bold**, _italic_, `code`"
    )
    update.message.reply_markdown_v2(escape_markdown_v2(txt))

def reset(update: Update, context: CallbackContext):
    send_typing(update, context)
    user = update.effective_user
    uname = (user.username or "").lower()
    if uname not in ADMIN_USERNAMES:
        return update.message.reply_markdown_v2(
            escape_markdown_v2("🚫 You are not allowed to reset history.")
        )
    data = ensure_user(update.effective_chat.id, user.username)
    data["history"].clear()
    data["tokens_today"] = 0
    update.message.reply_markdown_v2("*🔄 History and daily tokens have been reset!*")

def stats(update: Update, context: CallbackContext):
    send_typing(update, context)
    user = update.effective_user
    uname = (user.username or "").lower()
    data = ensure_user(update.effective_chat.id, user.username)
    used = data["tokens_today"]
    left = DAILY_TOKEN_LIMIT - used

    if uname in ADMIN_USERNAMES:
        total_users = len(all_users)
        total_msgs = sum(len(u["history"]) for u in user_data.values())
        text = (
            "🛡 *Admin Stats* 🛡\n\n"
            f"• Total Users: {total_users}\n"
            f"• Total Messages Stored: {total_msgs}\n"
            f"• Daily Token Limit: {DAILY_TOKEN_LIMIT}\n\n"
            "*Per-user usage:*\n"
        )
        for cid, udata in user_data.items():
            un = all_users.get(cid, str(cid))
            text += f"  – {un}: {udata['tokens_today']} tokens used\n"
        update.message.reply_markdown_v2(escape_markdown_v2(text))
    else:
        text = (
            "🕒 *Your Daily Token Usage* 🕒\n"
            f"• Used: {used}\n"
            f"• Remaining: {max(0,left)} of {DAILY_TOKEN_LIMIT}"
        )
        update.message.reply_markdown_v2(escape_markdown_v2(text))

def user_list(update: Update, context: CallbackContext):
    send_typing(update, context)
    user = update.effective_user
    if (user.username or "").lower() not in ADMIN_USERNAMES:
        return update.message.reply_markdown_v2(
            escape_markdown_v2("🚫 Access denied.")
        )
    text = "👥 *Current Users* 👥\n\n"
    for cid, uname in all_users.items():
        text += f"• {uname} (`{cid}`)\n"
    text += f"\n*Total:* {len(all_users)} users"
    update.message.reply_markdown_v2(escape_markdown_v2(text))

# ─── Message Handlers ─────────────────────────────────────────────────────────
def process_text(update: Update, context: CallbackContext):
    send_typing(update, context)
    if personality(update, context):
        return
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    data = ensure_user(chat_id, update.effective_user.username)
    if data["tokens_today"] >= DAILY_TOKEN_LIMIT:
        return update.message.reply_markdown_v2(
            escape_markdown_v2("⚠️ Daily token limit reached. Try again tomorrow!")
        )
    data["history"].append({"role":"user","parts":[{"text":text}]})
    reply, err, toks = call_gemini(data["history"])
    if err:
        return update.message.reply_text("Error: " + err)
    data["history"].append({"role":"model","parts":[{"text":reply}]})
    data["tokens_today"] += toks
    safe = escape_markdown_v2(reply)
    update.message.reply_text(safe, parse_mode=ParseMode.MARKDOWN_V2)

def process_photo(update: Update, context: CallbackContext):
    send_typing(update, context)
    chat_id = update.effective_chat.id
    data = ensure_user(chat_id, update.effective_user.username)
    if data["tokens_today"] >= DAILY_TOKEN_LIMIT:
        return update.message.reply_text("⚠️ Daily token limit reached.")
    caption = update.message.caption or ""
    photo = update.message.photo[-1].get_file()
    path = f"{photo.file_id}.jpg"; photo.download(path)
    with open(path, "rb") as f: img_b64 = base64.b64encode(f.read()).decode()
    os.remove(path)
    parts = [{"inline_data":{"mime_type":"image/jpeg","data":img_b64}}]
    if caption: parts.insert(0, {"text":caption})
    contents = [{"role":"user","parts":parts}]
    reply, err, toks = call_gemini(contents)
    if err:
        return update.message.reply_text("Error: " + err)
    data["history"].append({"role":"model","parts":[{"text":reply}]})
    data["tokens_today"] += toks
    safe = escape_markdown_v2(reply)
    update.message.reply_text(safe, parse_mode=ParseMode.MARKDOWN_V2)

def process_document(update: Update, context: CallbackContext):
    send_typing(update, context)
    chat_id = update.effective_chat.id
    data = ensure_user(chat_id, update.effective_user.username)
    if data["tokens_today"] >= DAILY_TOKEN_LIMIT:
        return update.message.reply_markdown_v2(
            escape_markdown_v2("⚠️ Daily token limit reached.")
        )
    doc = update.message.document
    caption = update.message.caption or ""
    file = doc.get_file(); path = doc.file_name; file.download(path)
    text = ""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext==".pdf" and fitz:
            pdf = fitz.open(path); text = "\n".join(p.get_text() for p in pdf)
        elif ext==".docx" and docx:
            d = docx.Document(path); text = "\n".join(p.text for p in d.paragraphs)
        elif ext==".txt":
            with open(path, encoding="utf-8") as f: text=f.read()
        else:
            return update.message.reply_text("Unsupported doc type.")
    except Exception as e:
        return update.message.reply_text("Read error: " + str(e))
    finally:
        os.remove(path)
    if "full text" in caption.lower():
        snippet = text[:4000] + ("...(truncated)" if len(text)>4000 else "")
        data["tokens_today"] += count_tokens(snippet)
        return update.message.reply_text(
            escape_markdown_v2(snippet), parse_mode=ParseMode.MARKDOWN_V2
        )
    prompt = "Summarize the following:\n\n" + text
    contents = [{"role":"user","parts":[{"text":prompt}]}]
    reply, err, toks = call_gemini(contents)
    if err:
        return update.message.reply_text("Error: " + err)
    data["history"].append({"role":"model","parts":[{"text":reply}]})
    data["tokens_today"] += toks
    safe = escape_markdown_v2(reply)
    update.message.reply_text(safe, parse_mode=ParseMode.MARKDOWN_V2)

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("features", features))
    dp.add_handler(CommandHandler("reset", reset))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CommandHandler("user", user_list))

    # Media
    dp.add_handler(MessageHandler(Filters.photo, process_photo))
    dp.add_handler(MessageHandler(Filters.document, process_document))

    # Chat
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, process_text))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

import telebot
from telebot import types
import subprocess
import os
import threading
import sys
import shutil
import time
import json

# Configuration
BOT_BUILDER_TOKEN = os.environ.get("BOT_BUILDER_TOKEN", "8005843427:AAFXLFu-lh7P0i8Ckojl1ySJHXX6y6xhtfU")
ADMIN_PASSWORD = "Harshit@9991207538"
ADMIN_USER_IDS = set()  # Store admin session user_ids

TEMPLATE_BOT_FILE = "starpy_v2.py"
USER_REGISTRY_FILE = "user_bots.json"
BROADCAST_FILE_PREFIX = "broadcast_message_"

bot = telebot.TeleBot(BOT_BUILDER_TOKEN, parse_mode="HTML")
user_states = {}

def load_user_registry():
    if not os.path.exists(USER_REGISTRY_FILE):
        return {}
    with open(USER_REGISTRY_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def save_user_registry(registry):
    with open(USER_REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

def register_user_bot(user_id, user_name, bot_token):
    registry = load_user_registry()
    if str(user_id) not in registry:
        # Get the username of the bot by token (call getMe)
        try:
            user_bot = telebot.TeleBot(bot_token)
            bot_info = user_bot.get_me()
            bot_username = bot_info.username
        except Exception:
            bot_username = "unknown"
        registry[str(user_id)] = {"user_id": user_id, "user_name": user_name, "bot_username": bot_username, "bot_token": bot_token}
        save_user_registry(registry)

def main_menu_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🚀 Make My Bot")
    kb.row("ℹ️ Help", "💬 Contact Support")
    kb.row("👑 Admin Panel")  # Shown to everyone, actual access is password-locked
    return kb

@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.send_message(
        message.chat.id,
        "👾 <b>Welcome to Bot Builder!</b>\n"
        "✨ <i>Make your own Telegram bot with just a few steps.</i>\n"
        "Press <b>🚀 Make My Bot</b> to get started!",
        reply_markup=main_menu_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == "ℹ️ Help")
def help_handler(message):
    bot.send_message(
        message.chat.id,
        "🛠 <b>How to use Bot Builder:</b>\n"
        "• Press <b>🚀 Make My Bot</b> and follow the steps.\n"
        "• Provide your Bot Token, Admin Password, and Payout Channel.\n"
        "• After setup, use <b>/admin</b> in your new bot to configure it!\n"
        "You can build unlimited bots!\n\n"
        "👤 <b>Contact Support:</b> @LeviAckerman_XD", reply_markup=main_menu_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == "💬 Contact Support")
def contact_support(message):
    bot.send_message(
        message.chat.id,
        "🙋‍♂️ <b>For help, contact:</b> @LeviAckerman_XD",
        reply_markup=main_menu_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == "🚀 Make My Bot")
def make_my_bot(message):
    user_id = message.from_user.id
    user_states[user_id] = {"step": "ask_token"}
    bot.send_message(
        message.chat.id,
        "🤖 <b>Let's build your bot!</b>\n"
        "Please send your <b>Bot Token</b> from @BotFather.",
        reply_markup=types.ReplyKeyboardRemove()
    )

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "ask_token")
def get_bot_token(message):
    token = message.text.strip()
    if not (":" in token and len(token) > 30):
        bot.send_message(message.chat.id, "❗️Invalid token. Please send a valid Bot Token from @BotFather.")
        return
    user_states[message.from_user.id]["token"] = token
    user_states[message.from_user.id]["step"] = "ask_password"
    bot.send_message(
        message.chat.id,
        "🔑 Now, set your <b>Admin Password</b> (for /admin access):"
    )

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "ask_password")
def get_admin_password(message):
    password = message.text.strip()
    if len(password) < 4:
        bot.send_message(message.chat.id, "❗️Password too short. Please send a longer password.")
        return
    user_states[message.from_user.id]["password"] = password
    user_states[message.from_user.id]["step"] = "ask_payout"
    bot.send_message(
        message.chat.id,
        "💸 Please send your <b>Payout Channel username</b> (e.g. @YourChannel):"
    )

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "ask_payout")
def get_payout_channel(message):
    payout = message.text.strip()
    if not payout.startswith("@") or " " in payout:
        bot.send_message(message.chat.id, "❗️Channel username must start with '@' and contain no spaces. Please try again.")
        return
    user_states[message.from_user.id]["payout"] = payout
    user_states[message.from_user.id]["step"] = "confirm"
    bot.send_message(
        message.chat.id,
        f"🎉 <b>All set!</b>\n\n"
        f"<b>Bot Token:</b> <code>{user_states[message.from_user.id]['token'][:8]}...{user_states[message.from_user.id]['token'][-6:]}</code>\n"
        f"<b>Admin Password:</b> <code>{user_states[message.from_user.id]['password']}</code>\n"
        f"<b>Payout Channel:</b> <code>{payout}</code>\n\n"
        "✅ <b>Your bot will be started now!</b>\n"
        "Type <b>/admin</b> in your new bot to access the admin panel.\n\n"
        "🛠 <b>If you face any problem, contact @LeviAckerman_XD</b> 😎",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )
    run_user_bot(message.from_user.id, message.from_user.username or str(message.from_user.id))

def run_user_bot(user_id, user_name):
    data = user_states.get(user_id)
    if not data: return
    token = data['token']
    password = data['password']
    payout = data['payout']

    user_bot_file = f"user{user_id}_starpy_v2.py"
    config_path = f"user{user_id}.env"

    # Copy the template script as a .py file
    shutil.copyfile(TEMPLATE_BOT_FILE, user_bot_file)

    # Create .env for the user's bot
    with open(config_path, "w") as f:
        f.write(f"BOT_TOKEN={token}\n")
        f.write(f"ADMIN_PASSWORD={password}\n")
        f.write(f"PAYOUT_CHANNEL={payout}\n")
        f.write(f"ADMIN_USERNAME=LeviAckerman_XD\n")

    register_user_bot(user_id, user_name, token)

    # Start the user's bot as a subprocess
    def launch():
        try:
            subprocess.Popen(
                [sys.executable, user_bot_file, config_path]
            )
        except Exception as e:
            print(f"[ERROR] Could not start user bot for {user_id}: {e}")

    threading.Thread(target=launch, daemon=True).start()

# Admin panel state
admin_sessions = {}

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    user_id = message.from_user.id
    msg = bot.send_message(message.chat.id, "🔑 Enter main admin password:")
    admin_sessions[user_id] = {"state": "awaiting_password"}
    bot.register_next_step_handler(msg, process_admin_password)

@bot.message_handler(func=lambda m: m.text == "👑 Admin Panel")
def admin_panel_menu_entry(message):
    return admin_cmd(message)

def process_admin_password(message):
    user_id = message.from_user.id
    state = admin_sessions.get(user_id, {})
    pwd = message.text.strip()
    if state.get("state") == "awaiting_password":
        if pwd == ADMIN_PASSWORD:
            admin_sessions[user_id] = {"state": "admin_panel"}
            ADMIN_USER_IDS.add(user_id)
            bot.send_message(message.chat.id, "✅ Welcome to the Bot Builder Admin Panel.", reply_markup=admin_panel_keyboard())
        else:
            bot.send_message(message.chat.id, "❌ Wrong password.")
            admin_sessions.pop(user_id, None)

def admin_panel_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("👥 List All Users", "📢 Broadcast to All Bots")
    kb.row("❌ Close Admin Panel")
    return kb

@bot.message_handler(func=lambda m: admin_sessions.get(m.from_user.id, {}).get("state") == "admin_panel" and m.text == "👥 List All Users")
def admin_list_users(message):
    registry = load_user_registry()
    if not registry:
        bot.send_message(message.chat.id, "No users have created bots yet.")
        return
    msg = "<b>Users & Their Bots:</b>\n"
    for user_data in registry.values():
        msg += f"👤 <b>{user_data['user_name']}</b> → 🤖 <b>@{user_data['bot_username']}</b>\n"
    bot.send_message(message.chat.id, msg, parse_mode="HTML")

@bot.message_handler(func=lambda m: admin_sessions.get(m.from_user.id, {}).get("state") == "admin_panel" and m.text == "📢 Broadcast to All Bots")
def admin_broadcast_start(message):
    msg = bot.send_message(message.chat.id, "📝 Send the message to broadcast to ALL user bots:")
    admin_sessions[message.from_user.id]["state"] = "awaiting_broadcast"
    bot.register_next_step_handler(msg, admin_broadcast_send)

def admin_broadcast_send(message):
    user_id = message.from_user.id
    text = message.text
    registry = load_user_registry()
    count = 0

    # Broadcast via dropfile: create a file for each bot, to be read by a bot subprocess (bot code must check for this file)
    for entry in registry.values():
        b_user_id = entry['user_id']
        dropfile = f"{BROADCAST_FILE_PREFIX}{b_user_id}.txt"
        try:
            with open(dropfile, "w", encoding="utf-8") as f:
                f.write(text)
            count += 1
        except Exception as e:
            print(f"[ERROR] Could not write broadcast for {b_user_id}: {e}")

    bot.send_message(message.chat.id, f"✅ Broadcast queued to {count} bots (will be delivered as soon as their bots next check for messages).")
    admin_sessions[user_id]["state"] = "admin_panel"

@bot.message_handler(func=lambda m: admin_sessions.get(m.from_user.id, {}).get("state") == "admin_panel" and m.text == "❌ Close Admin Panel")
def admin_panel_close(message):
    admin_sessions.pop(message.from_user.id, None)
    ADMIN_USER_IDS.discard(message.from_user.id)
    bot.send_message(message.chat.id, "🔒 Admin panel closed.", reply_markup=main_menu_keyboard())

# --- USER BOT BROADCAST HOOK ---
# Instruct users to add this snippet to the bottom of starpy_v2.py
"""
import threading, time, os
def check_broadcast():
    import telebot
    bot_token = os.environ.get("BOT_TOKEN")
    bot = telebot.TeleBot(bot_token, parse_mode="HTML")
    uid = bot.get_me().id
    dropfile = f"broadcast_message_{uid}.txt"
    while True:
        if os.path.exists(dropfile):
            with open(dropfile, "r", encoding="utf-8") as f:
                msg = f.read()
            for user in get_all_user_ids():  # You must implement get_all_user_ids()
                try:
                    bot.send_message(user, msg)
                except: pass
            os.remove(dropfile)
        time.sleep(10)
threading.Thread(target=check_broadcast, daemon=True).start()
"""
# (You must implement get_all_user_ids() in user bot, e.g., by reading all user IDs from the database.)

@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.send_message(
        message.chat.id,
        "🤖 Please use the menu below.",
        reply_markup=main_menu_keyboard()
    )

if __name__ == "__main__":
    print("Bot Builder is running...")
    bot.infinity_polling()

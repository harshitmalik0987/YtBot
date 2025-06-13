import telebot
from telebot import types
import subprocess
import os
import threading
import sys
import shutil

# Bot Builder's own token (change if needed)
BOT_BUILDER_TOKEN = os.environ.get("BOT_BUILDER_TOKEN", "6219450746:AAEZ04kRKNTDTguBLL-hqXBZKAFPMMnPty0")
bot = telebot.TeleBot(BOT_BUILDER_TOKEN, parse_mode="HTML")

user_states = {}

# Name of your actual template user bot file
TEMPLATE_BOT_FILE = "starpy_v2.py"  # Make sure your 674-line script is named starpy_v2.py

def main_menu_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🚀 Make My Bot")
    kb.row("ℹ️ Help", "💬 Contact Support")
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
    run_user_bot(message.from_user.id)

def run_user_bot(user_id):
    data = user_states.get(user_id)
    if not data: return
    token = data['token']
    password = data['password']
    payout = data['payout']

    # Unique file names per user
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

    # Start the user's bot as a subprocess (show errors in terminal for debug)
    def launch():
        try:
            subprocess.Popen(
                [sys.executable, user_bot_file, config_path]
            )
        except Exception as e:
            print(f"[ERROR] Could not start user bot for {user_id}: {e}")

    threading.Thread(target=launch, daemon=True).start()

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
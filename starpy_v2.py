import os
import sys
import telebot
from telebot import types
import sqlite3
from datetime import datetime
import json

# --- CONFIGURATION (DB-Backed) ---
DEFAULT_FORCE_CHANNELS = ["@GovtJobAIert", "@GovtjobAlertGrp", "@Airdrop_CIick"]
DEFAULT_SETTINGS = {
    "min_withdrawal": "5",
    "refer_reward": "1",
    "signup_bonus": "2",
    "currency_name": "TON",
    "currency_symbol": "💎",
    "admin_username": "LeviAckerman_XD"
}

if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    from dotenv import load_dotenv
    load_dotenv(sys.argv[1])

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    print("Error: BOT_TOKEN is not set in environment.")
    sys.exit(1)
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
PAYOUT_CHANNEL = os.environ.get("PAYOUT_CHANNEL", "@YourChannel")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "LeviAckerman_XD")

conn = sqlite3.connect('refer_earn_bot.db', check_same_thread=False)

# --- TABLE CREATION ---
with conn:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        points INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 0,
        joined_at TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        referrer_id INTEGER,
        referred_id INTEGER,
        PRIMARY KEY (referrer_id, referred_id)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        type TEXT,
        detail TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY,
        stars INTEGER,
        multiuse INTEGER DEFAULT 0,
        used_count INTEGER DEFAULT 0,
        max_uses INTEGER DEFAULT 1,
        used_by TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

# --- SETTINGS FUNCTIONS ---
def set_setting(key, value):
    with conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))

def get_setting(key, default=None):
    c = conn.cursor()
    try:
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        return row[0] if row else default
    finally:
        c.close()

def get_setting_json(key, default=None):
    v = get_setting(key)
    if v is None:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default

def set_setting_json(key, value):
    set_setting(key, json.dumps(value))

# --- INITIALIZE SETTINGS ---
if get_setting("force_channels") is None:
    set_setting_json("force_channels", DEFAULT_FORCE_CHANNELS)
for k, v in DEFAULT_SETTINGS.items():
    if get_setting(k) is None:
        set_setting(k, v)

def currency():
    return get_setting("currency_name", DEFAULT_SETTINGS["currency_name"])

def symbol():
    return get_setting("currency_symbol", DEFAULT_SETTINGS["currency_symbol"])

def admin_username():
    return get_setting("admin_username", DEFAULT_SETTINGS["admin_username"])

# --- FORCE JOIN FUNCTION ---
def get_channels():
    return get_setting_json("force_channels", DEFAULT_FORCE_CHANNELS)

def check_channels(user_id):
    channels = get_channels()
    for ch in channels:
        try:
            member = bot.get_chat_member(ch, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

# --- MAIN MENU ---
def user_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("💎 Balance", "🔗 Invite")
    kb.row("💰 Withdraw", "📊 Stats")
    kb.row("🎟️ Redeem Code", "🏆 Leaderboard")
    kb.row("ℹ️ Help")
    return kb

# --- START COMMAND ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    args = message.text.split()
    ref_id = None
    if len(args) > 1:
        try: ref_id = int(args[1])
        except: ref_id = None

    c = conn.cursor()
    try:
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        data = c.fetchone()
        signup_bonus = float(get_setting("signup_bonus", DEFAULT_SETTINGS["signup_bonus"]))
        refer_reward = float(get_setting("refer_reward", DEFAULT_SETTINGS["refer_reward"]))
        if not data:
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO users(user_id, username, points, joined_at) VALUES (?, ?, ?, ?)",
                    (user_id, username, int(signup_bonus*2), now))
            conn.commit()
            if ref_id and ref_id != user_id:
                c.execute("SELECT * FROM users WHERE user_id=?", (ref_id,))
                if c.fetchone():
                    try:
                        c.execute("INSERT INTO referrals(referrer_id, referred_id) VALUES(?, ?)", (ref_id, user_id))
                        c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (int(refer_reward*2), ref_id))
                        conn.commit()
                        try: bot.send_message(ref_id, f"🎉 You earned {refer_reward}{symbol()} for referring a new user!")
                        except: pass
                    except sqlite3.IntegrityError: pass
        else:
            c.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
            conn.commit()

        c.execute("SELECT verified FROM users WHERE user_id=?", (user_id,))
        verified = c.fetchone()[0]
    finally:
        c.close()

    if not verified:
        if check_channels(user_id):
            c = conn.cursor()
            try:
                c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
                conn.commit()
            finally:
                c.close()
            bot.send_message(user_id, "✅ Already joined all channels! You now have direct access.")
        else:
            markup = types.InlineKeyboardMarkup()
            btn = types.InlineKeyboardButton("✅ Verify Channels", callback_data="verify")
            markup.add(btn)
            chlist = "\n".join(get_channels())
            bot.send_message(user_id,
                f"🚨 Please join all the channels below to use this bot:\n{chlist}",
                reply_markup=markup)
            return

    bot.send_message(user_id,
       f"👋 Welcome, <b>{username}</b>! Select an option from the menu below:",
       reply_markup=user_menu())

@bot.callback_query_handler(func=lambda call: call.data == "verify")
def callback_verify(call):
    user_id = call.from_user.id
    if check_channels(user_id):
        c = conn.cursor()
        try:
            c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
            conn.commit()
        finally:
            c.close()
        bot.answer_callback_query(call.id, "Channels verified!")
        bot.send_message(user_id, "✅ Thank you! You now have access of bot.", reply_markup=user_menu())
    else:
        bot.answer_callback_query(call.id, "Not joined all channels yet.")
        bot.send_message(user_id, "❗️It looks like you're still missing one or more channels. Please join them and try again.")

@bot.message_handler(func=lambda m: m.text == "💎 Balance")
def show_balance(message):
    user_id = message.from_user.id
    c = conn.cursor()
    try:
        c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        points = result[0] if result else 0
        units = points / 2
        unit_str = f"{int(units)}" if points % 2 == 0 else f"{units:.1f}"
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
        ref_count = c.fetchone()[0]
    finally:
        c.close()
    bot.send_message(message.chat.id, f"💰 Your balance: <b>{unit_str}{symbol()}</b>\n👫 Referrals: <b>{ref_count}</b>")

@bot.message_handler(func=lambda m: m.text == "🔗 Invite")
def send_referral_link(message):
    user_id = message.from_user.id
    bot_info = bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user_id}"
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
        ref_count = c.fetchone()[0]
    finally:
        c.close()
    bot.send_message(message.chat.id,
        f"🔗 <b>Your referral link:</b>\n<code>{link}</code>\n\n"
        f"Share this link and earn {get_setting('refer_reward', DEFAULT_SETTINGS['refer_reward'])}{symbol()} for each new user!\n"
        f"👫 You have <b>{ref_count}</b> referrals."
    )

@bot.message_handler(func=lambda m: m.text == "📊 Stats")
def show_stats(message):
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM withdrawals")
        total_withdrawals = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM withdrawals")
        total_withdrawn = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM redeem_codes")
        total_codes = c.fetchone()[0]
    finally:
        c.close()
    bot.send_message(message.chat.id,
        f"📊 <b>Statistics</b>:\n"
        f"• Total Users: <b>{total_users}</b>\n"
        f"• Withdrawal Requests: <b>{total_withdrawals}</b>\n"
        f"• Total Redeem Codes: <b>{total_codes}</b>\n           🗣 Admin : @{admin_username()}"
    )

@bot.message_handler(func=lambda m: m.text == "ℹ️ Help")
def show_help(message):
    help_text = (
        f"💡 <b>How to use this bot:</b>\n"
        f"• Share your referral link to invite others and earn {symbol()}.\n"
        f"• Each new user you refer gives you +{get_setting('refer_reward', DEFAULT_SETTINGS['refer_reward'])}{symbol()}, and you also get {get_setting('signup_bonus',DEFAULT_SETTINGS['signup_bonus'])}{symbol()} as signup bonus!\n"
        f"• Use Balance to check your {currency()}s and referrals.\n"
        f"• When you have at least {get_setting('min_withdrawal',DEFAULT_SETTINGS['min_withdrawal'])}{symbol()}, click Withdraw to redeem {currency()}s.\n"
        f"• Withdraw to Channel: forward a post link to our channel.\n"
        f"• Withdraw to Account (requires ≥15{symbol()}): provide payment info to receive credit.\n"
        f"• View total users and withdrawals in Stats.\n"
        f"• Use Redeem Code to instantly add {currency()}s if you have a valid code!\n"
        f"• Check the 🏆 Leaderboard to see top users.\n       🗣 Admin : @{admin_username()}"
    )
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(func=lambda m: m.text == "💰 Withdraw")
def initiate_withdraw(message):
    user_id = message.from_user.id
    min_withdrawal = int(float(get_setting("min_withdrawal", DEFAULT_SETTINGS["min_withdrawal"])))
    c = conn.cursor()
    try:
        c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        points = c.fetchone()[0]
    finally:
        c.close()
    if points < min_withdrawal * 2:
        bot.send_message(message.chat.id,
            f"🚫 You need at least <b>{min_withdrawal}{symbol()}</b> to withdraw. Invite more users to earn {currency()}s!")
        return

    markup = types.InlineKeyboardMarkup()
    btn_channel = types.InlineKeyboardButton("🏷️ Withdraw to Channel", callback_data="withdraw_channel")
    btn_account = types.InlineKeyboardButton("🏧 Withdraw to Account", callback_data="withdraw_account")
    if points >= 30:
        markup.row(btn_channel, btn_account)
    else:
        markup.add(btn_channel)
    bot.send_message(user_id, "Please choose a withdrawal method:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "withdraw_channel")
def withdraw_to_channel_callback(call):
    user_id = call.from_user.id
    min_withdrawal = int(float(get_setting("min_withdrawal", DEFAULT_SETTINGS["min_withdrawal"])))
    c = conn.cursor()
    try:
        c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        points = c.fetchone()[0]
    finally:
        c.close()
    if points < min_withdrawal * 2:
        bot.answer_callback_query(call.id, "Not enough funds.")
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(user_id, f"Enter the amount of {symbol()} to withdraw (integer):")
    bot.register_next_step_handler(msg, process_withdraw_channel)

def process_withdraw_channel(message):
    try: units = int(message.text.strip())
    except: bot.send_message(message.chat.id, "⚠️ Please enter a valid integer amount."); return
    user_id = message.from_user.id
    min_withdrawal = int(float(get_setting("min_withdrawal", DEFAULT_SETTINGS["min_withdrawal"])))
    c = conn.cursor()
    try:
        c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        points = c.fetchone()[0]
    finally:
        c.close()
    if units < min_withdrawal or units*2 > points:
        bot.send_message(message.chat.id, f"🚫 Invalid amount or insufficient {currency()}s.")
        return
    ask_msg = bot.send_message(message.chat.id, "Send the post link (URL) you want to promote in the channel:")
    bot.register_next_step_handler(ask_msg, finish_withdraw_channel, units)

def finish_withdraw_channel(message, units):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    link = message.text.strip()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET points = points - ? WHERE user_id=?", (units*2, user_id))
        c.execute("INSERT INTO withdrawals(user_id, amount, type, detail) VALUES(?,?,?,?)",
                    (user_id, units, 'channel', link))
        conn.commit()
    finally:
        c.close()
    bot.send_message(PAYOUT_CHANNEL,
        f"💸 <b>Channel Withdraw</b>\nUser @{username} (ID:{user_id}) wants to withdraw {units}{symbol()}.\nPost link is forwarded below:")
    try:
        bot.forward_message(PAYOUT_CHANNEL, message.chat.id, message.message_id)
    except: pass
    bot.send_message(message.chat.id, f"✅ Your request to withdraw {units}{symbol()} to the channel has been submitted!")

@bot.callback_query_handler(func=lambda call: call.data == "withdraw_account")
def withdraw_to_account_callback(call):
    user_id = call.from_user.id
    c = conn.cursor()
    try:
        c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        points = c.fetchone()[0]
    finally:
        c.close()
    if points < 30:
        bot.answer_callback_query(call.id, f"You need at least 15{symbol()} for account withdrawals.")
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(user_id, f"Enter the amount of {symbol()} to withdraw (integer):")
    bot.register_next_step_handler(msg, process_withdraw_account)

def process_withdraw_account(message):
    try: units = int(message.text.strip())
    except: bot.send_message(message.chat.id, "⚠️ Please enter a valid integer amount."); return
    user_id = message.from_user.id
    c = conn.cursor()
    try:
        c.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        points = c.fetchone()[0]
    finally:
        c.close()
    if units < 1 or units*2 > points:
        bot.send_message(message.chat.id, f"🚫 Invalid amount or insufficient {currency()}s.")
        return
    ask_msg = bot.send_message(message.chat.id, "Send your username with @ (e.g @LeviAckerman_XD):")
    bot.register_next_step_handler(ask_msg, finish_withdraw_account, units)

def finish_withdraw_account(message, units):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    account_info = message.text.strip()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET points = points - ? WHERE user_id=?", (units*2, user_id))
        c.execute("INSERT INTO withdrawals(user_id, amount, type, detail) VALUES(?,?,?,?)",
                    (user_id, units, 'account', account_info))
        conn.commit()
    finally:
        c.close()
    bot.send_message(PAYOUT_CHANNEL,
        f"💸 <b>Account Withdraw</b>\nUser @{username} (ID:{user_id}) wants to withdraw {units}{symbol()} to their account. Details below:")
    try:
        bot.forward_message(PAYOUT_CHANNEL, message.chat.id, message.message_id)
    except: pass
    bot.send_message(message.chat.id, f"✅ Your request to withdraw {units}{symbol()} to your account has been submitted!")

@bot.message_handler(func=lambda m: m.text == "🎟️ Redeem Code")
def redeem_code_entry(message):
    msg = bot.send_message(message.chat.id, f"🎟️ <b>Enter your redeem code:</b>", parse_mode='HTML')
    bot.register_next_step_handler(msg, process_redeem_code)

def process_redeem_code(message):
    code = message.text.strip()
    user_id = message.from_user.id
    c = conn.cursor()
    try:
        c.execute("SELECT stars, multiuse, used_count, max_uses, used_by FROM redeem_codes WHERE code=?", (code,))
        row = c.fetchone()
        if not row:
            bot.send_message(message.chat.id, "❌ Invalid or expired code.")
            return
        stars, multiuse, used_count, max_uses, used_by = row
        used_by_list = used_by.split(',') if used_by else []
        if not multiuse and used_count >= 1:
            bot.send_message(message.chat.id, "❌ This code has already been redeemed.")
            return
        if multiuse and used_count >= max_uses:
            bot.send_message(message.chat.id, "❌ This code has reached its max uses.")
            return
        if str(user_id) in used_by_list:
            bot.send_message(message.chat.id, "❌ You have already used this code.")
            return
        c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (stars*2, user_id))
        new_used_by = (used_by + ',' if used_by else '') + str(user_id)
        c.execute("UPDATE redeem_codes SET used_count=used_count+1, used_by=? WHERE code=?",
            (new_used_by, code))
        conn.commit()
    finally:
        c.close()
    bot.send_message(message.chat.id, f"✅ Code redeemed! <b>{stars}{symbol()}</b> added to your balance.", parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def leaderboard(message):
    c = conn.cursor()
    try:
        c.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10")
        data = c.fetchall()
    finally:
        c.close()
    text = f"🏆 <b>Top 10 Users</b>\n"
    for i, (username, points) in enumerate(data, 1):
        units = points/2
        unit_str = f"{int(units)}" if points % 2 == 0 else f"{units:.1f}"
        text += f"{i}. <b>@{username}</b> - <b>{unit_str}{symbol()}</b>\n"
    bot.send_message(message.chat.id, text)

# --- ADMIN PANEL ---
admin_states = {}

@bot.message_handler(commands=['admin'])
def admin_login(message):
    user_id = message.from_user.id
    msg = bot.send_message(message.chat.id, "🔒 Enter admin password:")
    admin_states[user_id] = "awaiting_password"
    bot.register_next_step_handler(msg, process_admin_password)

def admin_panel_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ Create Redeem Code", "📢 Broadcast")
    kb.row("📋 List Redeem Codes", "📈 Admin Stats")
    kb.row("⚙️ Settings", "👥 Force Channels")
    kb.row("❌ Close Admin Panel")
    return kb

def process_admin_password(message):
    user_id = message.from_user.id
    pwd = message.text.strip()
    if admin_states.get(user_id) == "awaiting_password":
        if pwd == ADMIN_PASSWORD:
            admin_states[user_id] = "admin_panel"
            bot.send_message(message.chat.id, "✅ Welcome to the Admin Panel.", reply_markup=admin_panel_keyboard())
        else:
            del admin_states[user_id]
            bot.send_message(message.chat.id, "❌ Wrong password.")

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id) == "admin_panel" and m.text == "⚙️ Settings")
def admin_settings(message):
    min_withdrawal = get_setting("min_withdrawal", DEFAULT_SETTINGS["min_withdrawal"])
    refer_reward = get_setting("refer_reward", DEFAULT_SETTINGS["refer_reward"])
    signup_bonus = get_setting("signup_bonus", DEFAULT_SETTINGS["signup_bonus"])
    curname = get_setting("currency_name", DEFAULT_SETTINGS["currency_name"])
    cursym = get_setting("currency_symbol", DEFAULT_SETTINGS["currency_symbol"])
    adminuser = get_setting("admin_username", DEFAULT_SETTINGS["admin_username"])
    text = (
        f"<b>Settings:</b>\n"
        f"1️⃣ Minimum Withdrawal: {min_withdrawal}{cursym}\n"
        f"2️⃣ Referral Reward: {refer_reward}{cursym}\n"
        f"3️⃣ Signup Bonus: {signup_bonus}{cursym}\n"
        f"4️⃣ Currency Name: {curname}\n"
        f"5️⃣ Currency Symbol: {cursym}\n"
        f"6️⃣ Admin Username: @{adminuser}\n\n"
        "Reply with:\n"
        "<code>set min_withdrawal 5</code>\n"
        "<code>set refer_reward 1</code>\n"
        "<code>set signup_bonus 2</code>\n"
        "<code>set currency_name TON</code>\n"
        "<code>set currency_symbol 💎</code>\n"
        "<code>set admin_username NewAdmin</code>"
    )
    bot.send_message(message.chat.id, text, parse_mode='HTML')
    admin_states[message.from_user.id] = "awaiting_settings_cmd"

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id, "").startswith("awaiting_settings"))
def admin_settings_cmd(message):
    user_id = message.from_user.id
    parts = message.text.strip().split(maxsplit=2)
    if len(parts) == 3 and parts[0].lower() == "set":
        key, val = parts[1], parts[2]
        valid_keys = ["min_withdrawal", "refer_reward", "signup_bonus", "currency_name", "currency_symbol", "admin_username"]
        if key in valid_keys:
            set_setting(key, val)
            bot.send_message(message.chat.id, f"✅ {key.replace('_',' ').title()} set to <b>{val}</b>!", parse_mode="HTML")
            admin_states[user_id] = "admin_panel"
            return
    bot.send_message(message.chat.id, "❌ Invalid setting command. Please check and try again.")

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id) == "admin_panel" and m.text == "👥 Force Channels")
def admin_force_channels(message):
    chlist = get_channels()
    text = (
        "<b>Force Join Channels:</b>\n" +
        "\n".join([f"{idx+1}. {ch}" for idx, ch in enumerate(chlist)]) +
        "\n\nReply:\n"
        "<code>add @ChannelUsername</code> to add, "
        "<code>remove 1</code> to remove by number, or\n"
        "<code>reset</code> to restore default list."
    )
    bot.send_message(message.chat.id, text, parse_mode='HTML')
    admin_states[message.from_user.id] = "awaiting_force_channels"

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id, "").startswith("awaiting_force_channels"))
def admin_force_channels_cmd(message):
    user_id = message.from_user.id
    txt = message.text.strip()
    chlist = get_channels()
    if txt.lower().startswith("add "):
        ch = txt.split(None, 1)[1].strip()
        if ch not in chlist:
            chlist.append(ch)
            set_setting_json("force_channels", chlist)
            bot.send_message(message.chat.id, f"✅ Channel added: {ch}")
        else:
            bot.send_message(message.chat.id, "Channel already in list.")
    elif txt.lower().startswith("remove "):
        try:
            idx = int(txt.split(None,1)[1].strip()) - 1
            if 0 <= idx < len(chlist):
                removed = chlist.pop(idx)
                set_setting_json("force_channels", chlist)
                bot.send_message(message.chat.id, f"✅ Removed: {removed}")
            else:
                bot.send_message(message.chat.id, "Invalid index.")
        except:
            bot.send_message(message.chat.id, "Invalid remove command.")
    elif txt.lower() == "reset":
        set_setting_json("force_channels", DEFAULT_FORCE_CHANNELS)
        bot.send_message(message.chat.id, "✅ Force channels reset to default.")
    else:
        bot.send_message(message.chat.id, "Unrecognized command.")
    admin_states[user_id] = "admin_panel"

# --- Existing admin functions below unchanged, but all DB access is now cursor-local (see above for examples) ---

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id) == "admin_panel" and m.text == "➕ Create Redeem Code")
def admin_create_code_start(message):
    msg = bot.send_message(message.chat.id, "Enter a code (no spaces):")
    admin_states[message.from_user.id] = ("awaiting_code",)
    bot.register_next_step_handler(msg, admin_create_code_code)

def admin_create_code_code(message):
    code = message.text.strip().replace(" ", "")
    user_id = message.from_user.id
    if not code:
        bot.send_message(message.chat.id, "❌ Code cannot be empty.")
        return
    msg = bot.send_message(message.chat.id, f"How many {symbol()} (integer) for this code?")
    admin_states[user_id] = ("awaiting_stars", code)
    bot.register_next_step_handler(msg, admin_create_code_stars)

def admin_create_code_stars(message):
    user_id = message.from_user.id
    try: stars = int(message.text.strip())
    except: bot.send_message(message.chat.id, "❌ Invalid number of stars."); return
    if stars < 1:
        bot.send_message(message.chat.id, f"❌ {currency()}s must be at least 1.")
        return
    msg = bot.send_message(message.chat.id, "Multi-use? Reply Yes or No")
    state = admin_states.get(user_id)
    if state and state[0] == "awaiting_stars":
        code = state[1]
        admin_states[user_id] = ("awaiting_multiuse", code, stars)
        bot.register_next_step_handler(msg, admin_create_code_multiuse)

def admin_create_code_multiuse(message):
    user_id = message.from_user.id
    answer = message.text.strip().lower()
    state = admin_states.get(user_id)
    if state and state[0] == "awaiting_multiuse":
        code, stars = state[1], state[2]
        if answer in ["yes", "y"]:
            msg = bot.send_message(message.chat.id, "How many total uses allowed for this code?")
            admin_states[user_id] = ("awaiting_maxuses", code, stars)
            bot.register_next_step_handler(msg, admin_create_code_maxuses)
        elif answer in ["no", "n"]:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO redeem_codes (code, stars, multiuse, max_uses) VALUES (?, ?, 0, 1)", (code, stars))
                conn.commit()
                bot.send_message(message.chat.id, f"✅ Redeem code <b>{code}</b> created for <b>{stars}{symbol()}</b>!", parse_mode='HTML')
            except sqlite3.IntegrityError:
                bot.send_message(message.chat.id, "❌ This code already exists.")
            finally:
                c.close()
            admin_states[user_id] = "admin_panel"
        else:
            bot.send_message(message.chat.id, "❌ Please reply Yes or No.")

def admin_create_code_maxuses(message):
    user_id = message.from_user.id
    try: max_uses = int(message.text.strip())
    except: bot.send_message(message.chat.id, "❌ Invalid number of uses."); return
    state = admin_states.get(user_id)
    if state and state[0] == "awaiting_maxuses":
        code, stars = state[1], state[2]
        c = conn.cursor()
        try:
            c.execute("INSERT INTO redeem_codes (code, stars, multiuse, max_uses) VALUES (?, ?, 1, ?)", (code, stars, max_uses))
            conn.commit()
            bot.send_message(message.chat.id, f"✅ Multi-use redeem code <b>{code}</b> created for <b>{stars}{symbol()}</b>, max uses: <b>{max_uses}</b>!", parse_mode='HTML')
        except sqlite3.IntegrityError:
            bot.send_message(message.chat.id, "❌ This code already exists.")
        finally:
            c.close()
        admin_states[user_id] = "admin_panel"

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id) == "admin_panel" and m.text == "📢 Broadcast")
def admin_broadcast_start(message):
    msg = bot.send_message(message.chat.id, "Send the broadcast message to all users. (Text only!)")
    admin_states[message.from_user.id] = ("awaiting_broadcast",)
    bot.register_next_step_handler(msg, admin_broadcast_send)

def admin_broadcast_send(message):
    user_id = message.from_user.id
    text = message.text
    c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM users")
        all_users = [row[0] for row in c.fetchall()]
    finally:
        c.close()
    count = 0
    for uid in all_users:
        try:
            bot.send_message(uid, text)
            count += 1
        except:
            continue
    bot.send_message(message.chat.id, f"✅ Broadcast sent to {count} users.")
    admin_states[user_id] = "admin_panel"

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id) == "admin_panel" and m.text == "📋 List Redeem Codes")
def admin_list_codes(message):
    c = conn.cursor()
    try:
        c.execute("SELECT code, stars, multiuse, used_count, max_uses FROM redeem_codes ORDER BY created_at DESC LIMIT 20")
        rows = c.fetchall()
    finally:
        c.close()
    if not rows:
        bot.send_message(message.chat.id, "No codes in database.")
    else:
        s = ""
        for code, stars, multiuse, used_count, max_uses in rows:
            s += f"• <b>{code}</b>: {stars}{symbol()} | {'Multi' if multiuse else 'Single'} | {used_count}/{max_uses} used\n"
        bot.send_message(message.chat.id, s, parse_mode='HTML')
    admin_states[message.from_user.id] = "admin_panel"

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id) == "admin_panel" and m.text == "📈 Admin Stats")
def admin_stats(message):
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM withdrawals")
        total_withdrawals = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM withdrawals")
        total_withdrawn = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM redeem_codes")
        total_codes = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM redeem_codes WHERE multiuse=1")
        multi_codes = c.fetchone()[0]
    finally:
        c.close()
    bot.send_message(message.chat.id,
        f"👮 <b>Admin Stats</b>:\n"
        f"• Total Users: <b>{total_users}</b>\n"
        f"• Withdrawals: <b>{total_withdrawals}</b>\n"
        f"• Withdrawn: <b>{total_withdrawn}{symbol()}</b>\n"
        f"• Redeem Codes: <b>{total_codes}</b> (Multi-use: {multi_codes})",
        parse_mode='HTML')
    admin_states[message.from_user.id] = "admin_panel"

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id) == "admin_panel" and m.text == "❌ Close Admin Panel")
def close_admin_panel(message):
    del admin_states[message.from_user.id]
    bot.send_message(message.chat.id, "🔒 Admin panel closed.", reply_markup=user_menu())
    handle_start(message)  # Show normal user menu

@bot.message_handler(commands=['myrefs'])
def myrefs(message):
    user_id = message.from_user.id
    c = conn.cursor()
    try:
        c.execute("SELECT referred_id FROM referrals WHERE referrer_id=?", (user_id,))
        referred = c.fetchall()
        if not referred:
            bot.send_message(message.chat.id, "You have not referred anyone yet.")
            return
        text = "👫 <b>Your Referrals:</b>\n"
        for idx, row in enumerate(referred, 1):
            rid = row[0]
            c.execute("SELECT username FROM users WHERE user_id=?", (rid,))
            rname_row = c.fetchone()
            if rname_row and rname_row[0]:
                text += f"{idx}. @{rname_row[0]}\n"
            else:
                text += f"{idx}. User {rid}\n"
    finally:
        c.close()
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['profile'])
def profile(message):
    user_id = message.from_user.id
    c = conn.cursor()
    try:
        c.execute("SELECT username, points, joined_at FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
        if not row:
            bot.send_message(message.chat.id, "Profile not found!")
            return
        username, points, joined_at = row
        units = points / 2
        unit_str = f"{int(units)}" if points % 2 == 0 else f"{units:.1f}"
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
        ref_count = c.fetchone()[0]
    finally:
        c.close()
    bot.send_message(message.chat.id,
        f"👤 <b>Profile</b>\n"
        f"• Username: @{username}\n"
        f"• {currency()}s: <b>{unit_str}{symbol()}</b>\n"
        f"• Referrals: <b>{ref_count}</b>\n"
        f"• Joined: {joined_at}")

if __name__ == '__main__':
    print("Bot is running...")
    bot.infinity_polling()
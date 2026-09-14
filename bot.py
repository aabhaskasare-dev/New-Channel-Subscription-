import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# --- HARDCODED SETTINGS ---
FIXED_PRICE = "199"         # Fixed subscription price in INR
FIXED_DURATION_DAYS = 30     # Fixed subscription duration in Days
FIXED_MINUTES = 43200        # 30 Days converted to minutes (30 * 24 * 60)

# --- RENDER KEEP-ALIVE SERVER ---
app = Flask('')
@app.route('/')
def home(): 
    return "Bot is running and healthy!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web).start()

# --- CONFIGURATION (Environment Variables) ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
channels_col = db['channels']
users_col = db['users']

# --- ADMIN LOGIC ---

@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = message.from_user.id
    bot.clear_step_handler_by_chat_id(message.chat.id)
    
    text = message.text.split()

    # User entry via Deep Link
    if len(text) > 1:
        try:
            ch_id = int(text[1])
            ch_data = channels_col.find_one({"channel_id": ch_id})
            if ch_data:
                markup = InlineKeyboardMarkup()
                # Single fixed button: 30 Days @ ₹199
                markup.add(InlineKeyboardButton(f"💳 Pay ₹{FIXED_PRICE} for {FIXED_DURATION_DAYS} Days Access", callback_data=f"select_{ch_id}_{FIXED_MINUTES}"))
                markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
                
                bot.send_message(
                    message.chat.id, 
                    f"Welcome!\n\nYou are joining: *{ch_data['name']}*.\n\nClick below to proceed with your subscription:", 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
                return
        except Exception as e: 
            print(f"Deep link error: {e}")

    # Admin Panel Greeting
    if user_id == ADMIN_ID:
        bot.send_message(message.chat.id, "✅ Admin Panel Active!\n\n/add - Add Channel\n/channels - View Channels")
    else:
        bot.send_message(message.chat.id, "Welcome! To join a channel, please use the link provided by the Admin.")

@bot.message_handler(commands=['channels'], func=lambda m: m.from_user.id == ADMIN_ID)
def list_channels(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    markup = InlineKeyboardMarkup()
    cursor = channels_col.find({"admin_id": ADMIN_ID})
    count = 0
    for ch in cursor:
        markup.add(InlineKeyboardButton(f"Channel: {ch['name']}", callback_data=f"manage_{ch['channel_id']}"))
        count += 1
    
    markup.add(InlineKeyboardButton("➕ Add New Channel", callback_data="add_new"))
    
    if count == 0:
        bot.send_message(ADMIN_ID, "No channels found. Click below to add one.", reply_markup=markup)
    else:
        bot.send_message(ADMIN_ID, "Your Managed Channels:", reply_markup=markup)

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def add_channel_start(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    msg = bot.send_message(ADMIN_ID, "Please ensure the bot is an Admin in your channel, then FORWARD any message from that channel here.")
    bot.register_next_step_handler(msg, auto_finalize_channel)

@bot.callback_query_handler(func=lambda call: call.data == "add_new")
def cb_add_new(call):
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    msg = bot.send_message(ADMIN_ID, "Please FORWARD any message from your channel here.")
    bot.register_next_step_handler(msg, auto_finalize_channel)

def auto_finalize_channel(message):
    if message.forward_from_chat:
        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title
        
        # Save directly using preset price and duration
        channels_col.update_one(
            {"channel_id": ch_id}, 
            {"$set": {"name": ch_name, "price": FIXED_PRICE, "admin_id": ADMIN_ID}}, 
            upsert=True
        )
        
        bot_username = bot.get_me().username
        bot.send_message(
            ADMIN_ID, 
            f"✅ *Setup Successful!*\n\nChannel: *{ch_name}*\nPlan: *{FIXED_DURATION_DAYS} Days for ₹{FIXED_PRICE}*\n\nUser Invite Link:\n`https://t.me/{bot_username}?start={ch_id}`", 
            parse_mode="Markdown"
        )
    else:
        bot.send_message(ADMIN_ID, "❌ Error: Message was not forwarded. Use /add to try again.")

# --- USER: PAYMENT FLOW ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def user_pays(call):
    _, ch_id, mins = call.data.split('_')
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi://pay?pa={UPI_ID}%26am={FIXED_PRICE}%26cu=INR"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{ch_id}_{mins}"))
    markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
    
    bot.send_photo(
        call.message.chat.id, 
        qr_url, 
        caption=f"Plan: {FIXED_DURATION_DAYS} Days Access\nPrice: ₹{FIXED_PRICE}\nUPI ID: `{UPI_ID}`\n\nPlease complete the payment and click 'I Have Paid'.", 
        reply_markup=markup, 
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def admin_notify(call):
    _, ch_id, mins = call.data.split('_')
    user = call.from_user
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{ch_id}_{mins}"))
    markup.add(InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}"))
    
    bot.send_message(
        ADMIN_ID, 
        f"🔔 *Payment Verification Required!*\n\nUser: {user.first_name}\nChannel: {ch_data['name']}\nPlan: {FIXED_DURATION_DAYS} Days Access\nPrice: ₹{FIXED_PRICE}", 
        reply_markup=markup, 
        parse_mode="Markdown"
    )
    
    u_markup = InlineKeyboardMarkup().add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
    bot.send_message(call.message.chat.id, "✅ Your payment request has been sent. Please wait for Admin approval.", reply_markup=u_markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('rej_'))
def reject_now(call):
    u_id = int(call.data.split('_')[1])
    bot.send_message(u_id, "❌ Your payment verification request was rejected. Please contact support if you think this was an error.")
    bot.edit_message_text(f"❌ Rejected payment request for user {u_id}.", call.message.chat.id, call.message.message_id)

# --- APPROVAL & EXPIRY ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def approve_now(call):
    _, u_id, ch_id, mins = call.data.split('_')
    u_id, ch_id, mins = int(u_id), int(ch_id), int(mins)
    
    try:
        expiry_datetime = datetime.now() + timedelta(minutes=mins)
        expiry_ts = int(expiry_datetime.timestamp())

        # Link expires when subscription ends
        link = bot.create_chat_invite_link(ch_id, member_limit=1, expire_date=expiry_ts)
        
        users_col.update_one({"user_id": u_id, "channel_id": ch_id}, {"$set": {"expiry": expiry_datetime.timestamp()}}, upsert=True)
        
        bot.send_message(
            u_id, 
            f"🥳 *Payment Approved!*\n\nSubscription: {FIXED_DURATION_DAYS} Days Access\n\nJoin Link: {link.invite_link}\n\n⚠️ Note: This link and your channel access will expire in {FIXED_DURATION_DAYS} days.", 
            parse_mode="Markdown"
        )
        bot.edit_message_text(f"✅ Approved user {u_id} for {FIXED_DURATION_DAYS} Days access.", call.message.chat.id, call.message.message_id)
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Error creating invite link: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_'))
def manage_ch(call):
    ch_id = int(call.data.split('_')[1])
    ch_data = channels_col.find_one({"channel_id": ch_id})
    bot_username = bot.get_me().username
    link = f"https://t.me/{bot_username}?start={ch_id}"
    
    bot.edit_message_text(
        f"Settings for: *{ch_data['name']}*\nPrice: ₹{FIXED_PRICE} / {FIXED_DURATION_DAYS} Days\n\nYour Invite Link: `{link}`", 
        call.message.chat.id, 
        call.message.message_id, 
        parse_mode="Markdown"
    )

# Automate Kicking
def kick_expired_users():
    now = datetime.now().timestamp()
    expired_users = users_col.find({"expiry": {"$lte": now}})
    bot_username = bot.get_me().username

    for user in expired_users:
        try:
            bot.ban_chat_member(user['channel_id'], user['user_id'])
            bot.unban_chat_member(user['channel_id'], user['user_id'])
            
            rejoin_url = f"https://t.me/{bot_username}?start={user['channel_id']}"
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Re-join / Renew", url=rejoin_url))
            
            bot.send_message(user['user_id'], f"⚠️ Your {FIXED_DURATION_DAYS}-Day subscription has expired.\n\nTo join again or renew, please click the button below:", reply_markup=markup)
            users_col.delete_one({"_id": user['_id']})
        except Exception as e:
            print(f"Kick error: {e}")

# --- STARTUP ---
if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired_users, 'interval', minutes=1)
    scheduler.start()
    bot.remove_webhook()
    print("Bot is running...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

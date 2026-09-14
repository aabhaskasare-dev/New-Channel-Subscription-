import os
import sys
import logging
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- PRESET CONFIGURATION ---
FIXED_PRICE = "199"         # Fixed subscription price in INR
FIXED_DURATION_DAYS = 30     # Fixed duration in Days
FIXED_MINUTES = 43200        # 30 Days in minutes (30 * 24 * 60)

# --- ENVIRONMENT VARIABLES & VALIDATION ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
UPI_ID = os.getenv('UPI_ID')
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME')
ADMIN_ID_RAW = os.getenv('ADMIN_ID')

if not all([BOT_TOKEN, MONGO_URI, UPI_ID, CONTACT_USERNAME, ADMIN_ID_RAW]):
    logging.critical("CRITICAL ERROR: Environment variables missing on Render!")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID_RAW.strip())
except ValueError:
    logging.critical("CRITICAL ERROR: ADMIN_ID environment variable must be an integer.")
    sys.exit(1)

if CONTACT_USERNAME.startswith('@'):
    CONTACT_USERNAME = CONTACT_USERNAME[1:]

# --- RENDER KEEP-ALIVE SERVER ---
app = Flask('')
@app.route('/')
def home(): 
    return "Bot is running healthy!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# --- INITIALIZATION ---
bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['sub_management']
channels_col = db['channels']
users_col = db['users']

# Temporary in-memory state tracking to eliminate registration bugs
admin_adding_state = {}

# --- BOT HANDLERS ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    try:
        user_id = message.from_user.id
        admin_adding_state.pop(user_id, None)
        text = message.text.split()

        # Deep Link Entry (/start <channel_id>)
        if len(text) > 1:
            try:
                ch_id = int(text[1])
                ch_data = channels_col.find_one({"channel_id": ch_id})
                if ch_data:
                    ch_name = ch_data.get('name', 'VIP Channel')
                    markup = InlineKeyboardMarkup()
                    markup.add(InlineKeyboardButton(f"💳 Pay ₹{FIXED_PRICE} for {FIXED_DURATION_DAYS} Days Access", callback_data=f"select_{ch_id}_{FIXED_MINUTES}"))
                    markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
                    
                    bot.send_message(
                        message.chat.id, 
                        f"Welcome!\n\nYou are joining: *{ch_name}*.\n\nClick below to proceed with your subscription:", 
                        reply_markup=markup, 
                        parse_mode="Markdown"
                    )
                    return
            except Exception as dl_err:
                logging.error(f"Deep link processing error: {dl_err}")

        # Greeting Screen
        if user_id == ADMIN_ID:
            bot.send_message(message.chat.id, "✅ *Admin Panel Active!*\n\n/add - Add/Update Channel\n/channels - View Managed Channels", parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "Welcome! To join a channel, please use the invite link provided by the Admin.")
    except Exception as e:
        logging.error(f"Error in handle_start: {e}")

@bot.message_handler(commands=['channels'], func=lambda m: m.from_user.id == ADMIN_ID)
def handle_channels(message):
    try:
        admin_adding_state.pop(message.from_user.id, None)
        markup = InlineKeyboardMarkup()
        cursor = channels_col.find({"admin_id": ADMIN_ID})
        count = 0
        for ch in cursor:
            markup.add(InlineKeyboardButton(f"Channel: {ch.get('name', 'Unknown')}", callback_data=f"manage_{ch['channel_id']}"))
            count += 1
        
        markup.add(InlineKeyboardButton("➕ Add New Channel", callback_data="add_new"))
        
        if count == 0:
            bot.send_message(ADMIN_ID, "No channels found. Click below to add one.", reply_markup=markup)
        else:
            bot.send_message(ADMIN_ID, "Your Managed Channels:", reply_markup=markup)
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Database Error: `{str(e)}`", parse_mode="Markdown")

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def handle_add_command(message):
    admin_adding_state[message.from_user.id] = True
    bot.send_message(ADMIN_ID, "Please ensure the bot is an **Admin** in your channel, then **FORWARD** any message from that channel here.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "add_new")
def handle_add_callback(call):
    bot.answer_callback_query(call.id)
    admin_adding_state[call.from_user.id] = True
    bot.send_message(ADMIN_ID, "Please ensure the bot is an **Admin** in your channel, then **FORWARD** any message from that channel here.", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_adding_state.get(m.from_user.id, False), content_types=['text', 'photo', 'video', 'document'])
def handle_forwarded_message(message):
    try:
        admin_adding_state.pop(message.from_user.id, None)
        
        # Check all possible forward properties
        chat_obj = message.forward_from_chat or getattr(message, 'sender_chat', None)
        
        if chat_obj and chat_obj.type in ['channel', 'supergroup']:
            ch_id = chat_obj.id
            ch_name = chat_obj.title or "VIP Channel"
            
            channels_col.update_one(
                {"channel_id": ch_id}, 
                {"$set": {"name": ch_name, "price": FIXED_PRICE, "admin_id": ADMIN_ID}}, 
                upsert=True
            )
            
            bot_username = bot.get_me().username
            invite_link = f"https://t.me/{bot_username}?start={ch_id}"
            
            bot.send_message(
                ADMIN_ID, 
                f"✅ *Setup Successful!*\n\nChannel: *{ch_name}*\nPlan: *{FIXED_DURATION_DAYS} Days for ₹{FIXED_PRICE}*\n\nUser Share Link:\n`{invite_link}`", 
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                ADMIN_ID, 
                "❌ **Error:** Could not detect the channel details. Make sure you **FORWARD** a message directly from the channel.\n\nType /add to try again.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logging.error(f"Error saving channel: {e}")
        bot.send_message(ADMIN_ID, f"❌ **System Error:** `{str(e)}`", parse_mode="Markdown")

# --- PAYMENT FLOW ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def handle_payment_selection(call):
    try:
        bot.answer_callback_query(call.id)
        _, ch_id, mins = call.data.split('_')
        
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
    except Exception as e:
        logging.error(f"Error in handle_payment_selection: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def handle_paid_notification(call):
    try:
        bot.answer_callback_query(call.id)
        _, ch_id, mins = call.data.split('_')
        user = call.from_user
        ch_data = channels_col.find_one({"channel_id": int(ch_id)})
        ch_name = ch_data.get('name', 'VIP Channel') if ch_data else "VIP Channel"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{ch_id}_{mins}"))
        markup.add(InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}"))
        
        bot.send_message(
            ADMIN_ID, 
            f"🔔 *Payment Verification Required!*\n\nUser: {user.first_name} (@{user.username or 'No Username'})\nChannel: {ch_name}\nPlan: {FIXED_DURATION_DAYS} Days Access\nPrice: ₹{FIXED_PRICE}", 
            reply_markup=markup, 
            parse_mode="Markdown"
        )
        
        u_markup = InlineKeyboardMarkup().add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
        bot.send_message(call.message.chat.id, "✅ Your payment request has been sent. Please wait for Admin approval.", reply_markup=u_markup)
    except Exception as e:
        logging.error(f"Error in handle_paid_notification: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('rej_'))
def handle_rejection(call):
    try:
        bot.answer_callback_query(call.id)
        u_id = int(call.data.split('_')[1])
        bot.send_message(u_id, "❌ Your payment verification request was rejected. Please contact support if you think this was an error.")
        bot.edit_message_text(f"❌ Rejected payment request for user ID: {u_id}.", call.message.chat.id, call.message.message_id)
    except Exception as e:
        logging.error(f"Error in handle_rejection: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def handle_approval(call):
    try:
        bot.answer_callback_query(call.id)
        _, u_id, ch_id, mins = call.data.split('_')
        u_id, ch_id, mins = int(u_id), int(ch_id), int(mins)
        
        expiry_datetime = datetime.now() + timedelta(minutes=mins)
        expiry_ts = int(expiry_datetime.timestamp())

        link = bot.create_chat_invite_link(ch_id, member_limit=1, expire_date=expiry_ts)
        
        users_col.update_one({"user_id": u_id, "channel_id": ch_id}, {"$set": {"expiry": expiry_datetime.timestamp()}}, upsert=True)
        
        bot.send_message(
            u_id, 
            f"🥳 *Payment Approved!*\n\nSubscription: {FIXED_DURATION_DAYS} Days Access\n\nJoin Link: {link.invite_link}\n\n⚠️ Note: This link and your channel access will expire in {FIXED_DURATION_DAYS} days.", 
            parse_mode="Markdown"
        )
        bot.edit_message_text(f"✅ Approved user {u_id} for {FIXED_DURATION_DAYS} Days access.", call.message.chat.id, call.message.message_id)
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ **Error Creating Invite Link:** Make sure the bot is an **Admin** in the channel with *Invite Users via Link* permissions.\n\nDetails: `{str(e)}`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_'))
def handle_manage(call):
    try:
        bot.answer_callback_query(call.id)
        ch_id = int(call.data.split('_')[1])
        ch_data = channels_col.find_one({"channel_id": ch_id})
        bot_username = bot.get_me().username
        link = f"https://t.me/{bot_username}?start={ch_id}"
        ch_name = ch_data.get('name', 'VIP Channel') if ch_data else "VIP Channel"
        
        bot.edit_message_text(
            f"Settings for: *{ch_name}*\nPrice: ₹{FIXED_PRICE} / {FIXED_DURATION_DAYS} Days\n\nYour Shareable Invite Link:\n`{link}`", 
            call.message.chat.id, 
            call.message.message_id, 
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Error in handle_manage: {e}")

# --- EXPIRY SCHEDULER ---
def kick_expired_users():
    try:
        now = datetime.now().timestamp()
        expired_users = list(users_col.find({"expiry": {"$lte": now}}))
        bot_username = bot.get_me().username

        for user in expired_users:
            try:
                bot.ban_chat_member(user['channel_id'], user['user_id'])
                bot.unban_chat_member(user['channel_id'], user['user_id'])
                
                rejoin_url = f"https://t.me/{bot_username}?start={user['channel_id']}"
                markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Re-join / Renew", url=rejoin_url))
                
                bot.send_message(user['user_id'], f"⚠️ Your {FIXED_DURATION_DAYS}-Day subscription has expired.\n\nTo join again or renew, please click the button below:", reply_markup=markup)
                users_col.delete_one({"_id": user['_id']})
            except Exception as kick_err:
                logging.error(f"Kick execution error: {kick_err}")
                users_col.delete_one({"_id": user['_id']})
    except Exception as sched_err:
        logging.error(f"Scheduler error: {sched_err}")

# --- STARTUP EXECUTION ---
if __name__ == '__main__':
    keep_alive()
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired_users, 'interval', minutes=1)
    scheduler.start()
    
    try:
        bot.remove_webhook()
    except Exception as e:
        logging.warning(f"Webhook cleanup note: {e}")
        
    logging.info("Bot started running successfully.")
    bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)

import os
import sys
import logging
import telebot

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime
from flask import Flask
from threading import Thread
from urllib.parse import quote


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


# ============================================================
# FIXED MEMBERSHIP CONFIGURATION
# ============================================================

FIXED_PRICE = 199
MEMBERSHIP_TYPE = "Lifetime"


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
UPI_ID = os.getenv("UPI_ID")
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME")
ADMIN_ID_RAW = os.getenv("ADMIN_ID")


if not all([
    BOT_TOKEN,
    MONGO_URI,
    UPI_ID,
    CONTACT_USERNAME,
    ADMIN_ID_RAW
]):
    logging.critical(
        "CRITICAL ERROR: Missing environment variables on Render!"
    )
    sys.exit(1)


try:
    ADMIN_ID = int(ADMIN_ID_RAW.strip())
except ValueError:
    logging.critical(
        "CRITICAL ERROR: ADMIN_ID must be a valid integer."
    )
    sys.exit(1)


if CONTACT_USERNAME.startswith("@"):
    CONTACT_USERNAME = CONTACT_USERNAME[1:]


# ============================================================
# RENDER KEEP-ALIVE SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running healthy!"


def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port
    )


def keep_alive():
    Thread(
        target=run_web,
        daemon=True
    ).start()


# ============================================================
# BOT + DATABASE
# ============================================================

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000
)

db = client["sub_management"]

channels_col = db["channels"]
users_col = db["users"]
payments_col = db["payments"]


# Temporary admin setup state
admin_adding_state = {}


# ============================================================
# START COMMAND
# ============================================================

@bot.message_handler(commands=["start"])
def handle_start(message):

    try:

        user_id = message.from_user.id

        # Clear temporary admin state
        admin_adding_state.pop(user_id, None)

        text = message.text.split()

        # ----------------------------------------------------
        # DEEP LINK
        # ----------------------------------------------------

        if len(text) > 1:

            try:

                ch_id = int(text[1])

                ch_data = channels_col.find_one({
                    "channel_id": ch_id
                })

                if ch_data:

                    ch_name = ch_data.get(
                        "name",
                        "VIP Channel"
                    )

                    markup = InlineKeyboardMarkup()

                    markup.add(
                        InlineKeyboardButton(
                            "💎 Buy Lifetime Membership - ₹199",
                            callback_data=f"select_{ch_id}"
                        )
                    )

                    markup.add(
                        InlineKeyboardButton(
                            "📞 Contact Admin",
                            url=f"https://t.me/{CONTACT_USERNAME}"
                        )
                    )

                    bot.send_message(
                        message.chat.id,

                        f"👋 Welcome!\n\n"
                        f"You are joining:\n"
                        f"*{ch_name}*\n\n"
                        f"💎 Membership: *Lifetime*\n"
                        f"💰 Price: *₹{FIXED_PRICE}*\n\n"
                        f"Click below to continue.",

                        reply_markup=markup,
                        parse_mode="Markdown"
                    )

                    return

            except Exception as deep_link_error:

                logging.error(
                    f"Deep link error: {deep_link_error}"
                )


        # ----------------------------------------------------
        # ADMIN START
        # ----------------------------------------------------

        if user_id == ADMIN_ID:

            markup = InlineKeyboardMarkup()

            markup.add(
                InlineKeyboardButton(
                    "➕ Add / Update Channel",
                    callback_data="add_new"
                )
            )

            markup.add(
                InlineKeyboardButton(
                    "📋 My Channels",
                    callback_data="show_channels"
                )
            )

            bot.send_message(
                message.chat.id,

                "✅ *Admin Panel*\n\n"
                "Membership price: *₹199*\n"
                "Membership type: *Lifetime*\n\n"
                "Choose an option below.",

                reply_markup=markup,
                parse_mode="Markdown"
            )

        else:

            bot.send_message(
                message.chat.id,

                "👋 Welcome!\n\n"
                "To join the premium channel, please use "
                "the membership link provided by the administrator."
            )

    except Exception as e:

        logging.error(
            f"Error in /start: {e}"
        )


# ============================================================
# CHANNEL LIST
# ============================================================

@bot.message_handler(
    commands=["channels"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def handle_channels(message):

    try:

        admin_adding_state.pop(
            message.from_user.id,
            None
        )

        markup = InlineKeyboardMarkup()

        cursor = channels_col.find({
            "admin_id": ADMIN_ID
        })

        count = 0

        for channel in cursor:

            markup.add(
                InlineKeyboardButton(
                    f"📢 {channel.get('name', 'Unknown')}",
                    callback_data=f"manage_{channel['channel_id']}"
                )
            )

            count += 1

        markup.add(
            InlineKeyboardButton(
                "➕ Add New Channel",
                callback_data="add_new"
            )
        )

        if count == 0:

            bot.send_message(
                ADMIN_ID,
                "No channels found.\n\n"
                "Click below to add a channel.",
                reply_markup=markup
            )

        else:

            bot.send_message(
                ADMIN_ID,
                "📋 *Your Managed Channels*",
                reply_markup=markup,
                parse_mode="Markdown"
            )

    except Exception as e:

        bot.send_message(
            ADMIN_ID,
            f"❌ Database Error:\n`{str(e)}`",
            parse_mode="Markdown"
        )


# ============================================================
# /ADD COMMAND
# ============================================================

@bot.message_handler(
    commands=["add"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def handle_add_command(message):

    admin_adding_state[
        message.from_user.id
    ] = True

    bot.send_message(
        ADMIN_ID,

        "📢 *Add Channel*\n\n"
        "1. Make sure the bot is an *Administrator* "
        "in your Telegram channel.\n\n"
        "2. Give it permission to invite users.\n\n"
        "3. *Forward any message from that channel to me.*\n\n"
        "I will automatically detect the channel.",

        parse_mode="Markdown"
    )


# ============================================================
# ADD CHANNEL BUTTON
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "add_new"
)
def handle_add_callback(call):

    bot.answer_callback_query(call.id)

    admin_adding_state[
        call.from_user.id
    ] = True

    bot.send_message(
        ADMIN_ID,

        "📢 *Add Channel*\n\n"
        "Make sure the bot is an Administrator "
        "in your channel.\n\n"
        "Now *forward any message from the channel "
        "to this bot*.",

        parse_mode="Markdown"
    )


# ============================================================
# SHOW CHANNELS BUTTON
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "show_channels"
)
def handle_show_channels(call):

    bot.answer_callback_query(call.id)

    try:

        markup = InlineKeyboardMarkup()

        cursor = channels_col.find({
            "admin_id": ADMIN_ID
        })

        count = 0

        for channel in cursor:

            markup.add(
                InlineKeyboardButton(
                    f"📢 {channel.get('name', 'Unknown')}",
                    callback_data=f"manage_{channel['channel_id']}"
                )
            )

            count += 1

        markup.add(
            InlineKeyboardButton(
                "➕ Add New Channel",
                callback_data="add_new"
            )
        )

        if count == 0:

            bot.send_message(
                ADMIN_ID,
                "No channels configured.",
                reply_markup=markup
            )

        else:

            bot.send_message(
                ADMIN_ID,
                "📋 *Your Channels*",
                reply_markup=markup,
                parse_mode="Markdown"
            )

    except Exception as e:

        logging.error(
            f"Channel list error: {e}"
        )


# ============================================================
# FORWARDED CHANNEL MESSAGE
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.from_user.id == ADMIN_ID
        and admin_adding_state.get(
            m.from_user.id,
            False
        ),
    content_types=[
        "text",
        "photo",
        "video",
        "document"
    ]
)
def handle_forwarded_message(message):

    try:

        admin_adding_state.pop(
            message.from_user.id,
            None
        )

        # Telegram can expose forwarded channel
        # through different properties.

        chat_obj = (
            message.forward_from_chat
            or getattr(
                message,
                "sender_chat",
                None
            )
        )

        if not chat_obj:

            bot.send_message(
                ADMIN_ID,

                "❌ I could not detect the channel.\n\n"
                "Please use /add and forward a message "
                "*directly from the channel*.",

                parse_mode="Markdown"
            )

            return

        if chat_obj.type not in [
            "channel",
            "supergroup"
        ]:

            bot.send_message(
                ADMIN_ID,
                "❌ The forwarded message is not from "
                "a supported channel."
            )

            return

        ch_id = chat_obj.id

        ch_name = (
            chat_obj.title
            or "VIP Channel"
        )

        # Save channel
        channels_col.update_one(

            {
                "channel_id": ch_id
            },

            {
                "$set": {
                    "name": ch_name,
                    "price": FIXED_PRICE,
                    "membership": "Lifetime",
                    "admin_id": ADMIN_ID,
                    "updated_at": datetime.utcnow()
                }
            },

            upsert=True
        )

        # Generate bot deep link
        bot_username = bot.get_me().username

        invite_link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start={ch_id}"
        )

        bot.send_message(

            ADMIN_ID,

            f"✅ *Channel Setup Successful!*\n\n"

            f"📢 Channel: *{ch_name}*\n"
            f"💎 Membership: *Lifetime*\n"
            f"💰 Price: *₹{FIXED_PRICE}*\n\n"

            f"🔗 *Share this link with users:*\n"
            f"`{invite_link}`",

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Error saving channel: {e}"
        )

        bot.send_message(
            ADMIN_ID,
            f"❌ System Error:\n`{str(e)}`",
            parse_mode="Markdown"
        )


# ============================================================
# PAYMENT SELECTION
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("select_")
)
def handle_payment_selection(call):

    try:

        bot.answer_callback_query(call.id)

        ch_id = int(
            call.data.split("_")[1]
        )

        ch_data = channels_col.find_one({
            "channel_id": ch_id
        })

        if not ch_data:

            bot.send_message(
                call.message.chat.id,
                "❌ Channel information not found."
            )

            return

        # ----------------------------------------------------
        # UPI PAYMENT STRING
        # ----------------------------------------------------

        upi_string = (
            f"upi://pay?"
            f"pa={quote(UPI_ID)}"
            f"&am={FIXED_PRICE}"
            f"&cu=INR"
        )

        qr_url = (
            "https://api.qrserver.com/v1/create-qr-code/"
            f"?size=400x400&data={quote(upi_string)}"
        )

        markup = InlineKeyboardMarkup()

        markup.add(
            InlineKeyboardButton(
                "✅ I Have Paid",
                callback_data=f"paid_{ch_id}"
            )
        )

        markup.add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=f"https://t.me/{CONTACT_USERNAME}"
            )
        )

        bot.send_photo(

            call.message.chat.id,

            qr_url,

            caption=(
                f"💎 *Lifetime Membership*\n\n"
                f"💰 Amount: *₹{FIXED_PRICE}*\n"
                f"📱 UPI ID: `{UPI_ID}`\n\n"
                f"Scan the QR code and complete the payment.\n\n"
                f"After payment, click *I Have Paid*."
            ),

            reply_markup=markup,

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Payment selection error: {e}"
        )


# ============================================================
# USER SAYS "I HAVE PAID"
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("paid_")
)
def handle_paid_notification(call):

    try:

        bot.answer_callback_query(
            call.id,
            "Payment request sent to admin."
        )

        ch_id = int(
            call.data.split("_")[1]
        )

        user = call.from_user

        ch_data = channels_col.find_one({
            "channel_id": ch_id
        })

        ch_name = (
            ch_data.get(
                "name",
                "VIP Channel"
            )
            if ch_data
            else "VIP Channel"
        )

        # ----------------------------------------------------
        # CHECK EXISTING PAYMENT
        # ----------------------------------------------------

        existing_payment = payments_col.find_one({

            "user_id": user.id,

            "channel_id": ch_id,

            "status": "pending"

        })

        if existing_payment:

            bot.send_message(

                call.message.chat.id,

                "⏳ Your payment request is already "
                "waiting for admin approval.\n\n"
                "Please wait."
            )

            return

        # ----------------------------------------------------
        # CREATE PAYMENT RECORD
        # ----------------------------------------------------

        payment_data = {

            "user_id": user.id,

            "username": user.username,

            "first_name": user.first_name,

            "channel_id": ch_id,

            "channel_name": ch_name,

            "amount": FIXED_PRICE,

            "membership": "Lifetime",

            "status": "pending",

            "created_at": datetime.utcnow()

        }

        result = payments_col.insert_one(
            payment_data
        )

        payment_id = str(
            result.inserted_id
        )

        # ----------------------------------------------------
        # ADMIN APPROVAL BUTTONS
        # ----------------------------------------------------

        markup = InlineKeyboardMarkup()

        markup.row(

            InlineKeyboardButton(
                "✅ APPROVE",
                callback_data=(
                    f"app_{user.id}_{ch_id}_{payment_id}"
                )
            ),

            InlineKeyboardButton(
                "❌ REJECT",
                callback_data=(
                    f"rej_{user.id}_{payment_id}"
                )
            )

        )

        username_display = (
            f"@{user.username}"
            if user.username
            else "No Username"
        )

        bot.send_message(

            ADMIN_ID,

            f"🔔 *PAYMENT VERIFICATION*\n\n"

            f"👤 User: *{user.first_name}*\n"
            f"📱 Username: {username_display}\n"
            f"🆔 User ID: `{user.id}`\n\n"

            f"📢 Channel: *{ch_name}*\n"
            f"💎 Membership: *Lifetime*\n"
            f"💰 Amount: *₹{FIXED_PRICE}*\n\n"

            f"🆔 Payment ID:\n`{payment_id}`\n\n"

            f"Please verify the payment in your "
            f"UPI/bank account before approving.",

            reply_markup=markup,

            parse_mode="Markdown"
        )

        # ----------------------------------------------------
        # USER MESSAGE
        # ----------------------------------------------------

        user_markup = InlineKeyboardMarkup()

        user_markup.add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=f"https://t.me/{CONTACT_USERNAME}"
            )
        )

        bot.send_message(

            call.message.chat.id,

            "✅ *Payment request submitted!*\n\n"
            "Your payment is now waiting for "
            "manual verification by the administrator.\n\n"
            "You will receive your lifetime channel "
            "access link after approval.",

            reply_markup=user_markup,

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Payment notification error: {e}"
        )


# ============================================================
# REJECT PAYMENT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("rej_")
)
def handle_rejection(call):

    try:

        bot.answer_callback_query(
            call.id,
            "Payment rejected."
        )

        parts = call.data.split("_")

        user_id = int(parts[1])
        payment_id = parts[2]

        # Update payment
        payments_col.update_one(

            {
                "_id": __import__(
                    "bson"
                ).ObjectId(payment_id)
            },

            {
                "$set": {
                    "status": "rejected",
                    "rejected_at": datetime.utcnow()
                }
            }
        )

        # Notify user
        bot.send_message(

            user_id,

            "❌ *Payment Not Approved*\n\n"
            "Your payment could not be verified.\n\n"
            "If you have completed the payment, "
            "please contact the administrator.",

            parse_mode="Markdown"
        )

        bot.edit_message_text(

            f"❌ *Payment Rejected*\n\n"
            f"User ID: `{user_id}`\n"
            f"Payment ID: `{payment_id}`",

            call.message.chat.id,

            call.message.message_id,

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Rejection error: {e}"
        )


# ============================================================
# APPROVE PAYMENT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("app_")
)
def handle_approval(call):

    try:

        bot.answer_callback_query(
            call.id,
            "Payment approved!"
        )

        parts = call.data.split("_")

        user_id = int(parts[1])
        ch_id = int(parts[2])
        payment_id = parts[3]

        # ----------------------------------------------------
        # CHECK PAYMENT
        # ----------------------------------------------------

        from bson import ObjectId

        payment = payments_col.find_one({
            "_id": ObjectId(payment_id)
        })

        if not payment:

            bot.send_message(
                ADMIN_ID,
                "❌ Payment record not found."
            )

            return

        if payment.get("status") != "pending":

            bot.send_message(
                ADMIN_ID,
                "⚠️ This payment has already been processed."
            )

            return

        # ----------------------------------------------------
        # CREATE LIFETIME INVITE LINK
        # ----------------------------------------------------

        # IMPORTANT:
        # No expire_date is supplied.
        # Therefore the invite link does not expire.

        link = bot.create_chat_invite_link(

            ch_id,

            member_limit=1

        )

        # ----------------------------------------------------
        # UPDATE PAYMENT
        # ----------------------------------------------------

        payments_col.update_one(

            {
                "_id": ObjectId(payment_id)
            },

            {
                "$set": {

                    "status": "approved",

                    "approved_at": datetime.utcnow(),

                    "approved_by": ADMIN_ID

                }
            }
        )

        # ----------------------------------------------------
        # SAVE USER MEMBERSHIP
        # ----------------------------------------------------

        users_col.update_one(

            {
                "user_id": user_id,

                "channel_id": ch_id

            },

            {

                "$set": {

                    "user_id": user_id,

                    "channel_id": ch_id,

                    "membership": "Lifetime",

                    "status": "active",

                    "payment_id": payment_id,

                    "approved_at": datetime.utcnow(),

                    "invite_link": link.invite_link

                }

            },

            upsert=True
        )

        # ----------------------------------------------------
        # SEND LINK TO USER
        # ----------------------------------------------------

        bot.send_message(

            user_id,

            f"🎉 *PAYMENT APPROVED!*\n\n"

            f"💎 Membership: *Lifetime*\n"
            f"💰 Amount Paid: *₹{FIXED_PRICE}*\n\n"

            f"🔗 *Your private channel invite link:*\n\n"
            f"{link.invite_link}\n\n"

            f"⚠️ This invite is limited to your account "
            f"and does not expire.\n\n"

            f"Welcome! 🎉",

            parse_mode="Markdown"
        )

        # ----------------------------------------------------
        # UPDATE ADMIN MESSAGE
        # ----------------------------------------------------

        bot.edit_message_text(

            f"✅ *PAYMENT APPROVED*\n\n"

            f"👤 User ID: `{user_id}`\n"
            f"💰 Amount: ₹{FIXED_PRICE}\n"
            f"💎 Membership: Lifetime\n\n"
            f"🔗 Lifetime invite generated successfully.",

            call.message.chat.id,

            call.message.message_id,

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Approval error: {e}"
        )

        bot.send_message(

            ADMIN_ID,

            f"❌ *Could not approve payment.*\n\n"
            f"Make sure the bot is an administrator "
            f"in the channel and has permission to "
            f"invite users.\n\n"
            f"Error:\n`{str(e)}`",

            parse_mode="Markdown"
        )


# ============================================================
# MANAGE CHANNEL
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("manage_")
)
def handle_manage(call):

    try:

        bot.answer_callback_query(call.id)

        ch_id = int(
            call.data.split("_")[1]
        )

        ch_data = channels_col.find_one({
            "channel_id": ch_id
        })

        if not ch_data:

            bot.send_message(
                ADMIN_ID,
                "❌ Channel not found."
            )

            return

        bot_username = bot.get_me().username

        link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start={ch_id}"
        )

        ch_name = ch_data.get(
            "name",
            "VIP Channel"
        )

        bot.edit_message_text(

            f"📢 *Channel Settings*\n\n"

            f"Channel: *{ch_name}*\n"
            f"Membership: *Lifetime*\n"
            f"Price: *₹{FIXED_PRICE}*\n\n"

            f"🔗 *Shareable Bot Link:*\n"
            f"`{link}`",

            call.message.chat.id,

            call.message.message_id,

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Manage channel error: {e}"
        )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    keep_alive()

    try:

        bot.remove_webhook()

    except Exception as e:

        logging.warning(
            f"Webhook cleanup note: {e}"
        )

    logging.info(
        "Lifetime subscription bot started successfully."
    )

    bot.infinity_polling(
        timeout=20,
        long_polling_timeout=10,
        skip_pending=True
                    )

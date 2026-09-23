import os
import sys
import logging
from datetime import datetime
from threading import Thread
from urllib.parse import quote

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from bson import ObjectId
from flask import Flask


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
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
        "CRITICAL ERROR: Required environment variables are missing."
    )
    sys.exit(1)


try:
    ADMIN_ID = int(ADMIN_ID_RAW.strip())
except ValueError:
    logging.critical(
        "CRITICAL ERROR: ADMIN_ID must be a valid integer."
    )
    sys.exit(1)


# Remove @ if the admin entered it
if CONTACT_USERNAME.startswith("@"):
    CONTACT_USERNAME = CONTACT_USERNAME[1:]


# ============================================================
# RENDER WEB SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Telegram Membership Bot is running!"


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
# TELEGRAM BOT
# ============================================================

bot = telebot.TeleBot(BOT_TOKEN)


# ============================================================
# MONGODB
# ============================================================

try:

    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000
    )

    # Test MongoDB connection
    client.admin.command("ping")

    db = client["sub_management"]

    channels_col = db["channels"]
    users_col = db["users"]
    payments_col = db["payments"]
    settings_col = db["settings"]

    logging.info("MongoDB connected successfully.")

except Exception as e:

    logging.critical(
        f"MongoDB connection failed: {e}"
    )

    sys.exit(1)


# ============================================================
# TEMPORARY ADMIN STATES
# ============================================================

# Used when admin is adding a channel
admin_adding_state = {}

# Used when admin is setting the customer delivery message
admin_setting_message = {}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_delivery_message():

    return settings_col.find_one({
        "setting": "delivery_message"
    })


def contact_admin_button():

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    return markup


# ============================================================
# /START
# ============================================================

@bot.message_handler(commands=["start"])
def handle_start(message):

    try:

        user_id = message.from_user.id

        # Clear temporary states
        admin_adding_state.pop(user_id, None)
        admin_setting_message.pop(user_id, None)

        command_parts = message.text.split()

        # ====================================================
        # CUSTOMER DEEP LINK
        # ====================================================

        if len(command_parts) > 1:

            try:

                channel_id = int(command_parts[1])

                channel_data = channels_col.find_one({
                    "channel_id": channel_id
                })

                if channel_data:

                    channel_name = channel_data.get(
                        "name",
                        "Premium Channel"
                    )

                    markup = InlineKeyboardMarkup()

                    markup.add(
                        InlineKeyboardButton(
                            "💎 Buy Lifetime Membership - ₹199",
                            callback_data=f"select_{channel_id}"
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

                        f"👋 *Welcome!*\n\n"
                        f"You are joining:\n"
                        f"*{channel_name}*\n\n"
                        f"💎 Membership: *Lifetime*\n"
                        f"💰 Price: *₹{FIXED_PRICE}*\n\n"
                        f"Click below to proceed with your membership.",

                        reply_markup=markup,

                        parse_mode="Markdown"
                    )

                    return

            except Exception as e:

                logging.error(
                    f"Deep link error: {e}"
                )


        # ====================================================
        # ADMIN PANEL
        # ====================================================

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

            markup.add(
                InlineKeyboardButton(
                    "📩 Set Customer Message",
                    callback_data="set_delivery_message"
                )
            )

            bot.send_message(

                message.chat.id,

                "✅ *Admin Panel*\n\n"

                f"💰 Price: *₹{FIXED_PRICE}*\n"
                f"💎 Membership: *{MEMBERSHIP_TYPE}*\n\n"

                "Choose an option:",

                reply_markup=markup,

                parse_mode="Markdown"
            )

        else:

            bot.send_message(

                message.chat.id,

                "👋 Welcome!\n\n"
                "Please use the membership link provided "
                "by the administrator to continue."
            )

    except Exception as e:

        logging.error(
            f"Error in /start: {e}"
        )


# ============================================================
# /CHANNELS
# ============================================================

@bot.message_handler(
    commands=["channels"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def handle_channels(message):

    try:

        admin_adding_state.pop(
            ADMIN_ID,
            None
        )

        admin_setting_message.pop(
            ADMIN_ID,
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
                "Click below to add one.",
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

        logging.error(
            f"Channels error: {e}"
        )

        bot.send_message(
            ADMIN_ID,
            f"❌ Database Error:\n`{str(e)}`",
            parse_mode="Markdown"
        )


# ============================================================
# /ADD
# ============================================================

@bot.message_handler(
    commands=["add"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def handle_add_command(message):

    admin_adding_state[ADMIN_ID] = True

    bot.send_message(

        ADMIN_ID,

        "📢 *Add / Update Channel*\n\n"

        "First make sure this bot is an "
        "*Administrator* in your Telegram channel.\n\n"

        "Make sure it has permission to invite users.\n\n"

        "Now *forward any message from your channel "
        "to this bot*.\n\n"

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

    admin_adding_state[ADMIN_ID] = True

    bot.send_message(

        ADMIN_ID,

        "📢 *Add / Update Channel*\n\n"

        "Make sure the bot is an Administrator "
        "in your channel.\n\n"

        "Now *forward any message from that channel "
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
            f"Show channels error: {e}"
        )


# ============================================================
# SET DELIVERY MESSAGE
# ============================================================

@bot.message_handler(
    commands=["setmessage"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def handle_set_message(message):

    admin_setting_message[ADMIN_ID] = True

    # Make sure we're not simultaneously waiting for channel
    admin_adding_state.pop(
        ADMIN_ID,
        None
    )

    bot.send_message(

        ADMIN_ID,

        "📩 *Set Customer Delivery Message*\n\n"

        "Send me the exact message you want "
        "customers to receive after you approve "
        "their payment.\n\n"

        "You can send:\n"
        "• Text\n"
        "• Photo\n"
        "• Video\n"
        "• Document\n"
        "• Audio\n"
        "• Animation\n\n"

        "You can also include your own links/buttons "
        "where applicable.\n\n"

        "Use /setmessage again whenever you want "
        "to replace the current delivery message.",

        parse_mode="Markdown"
    )


# ============================================================
# SET DELIVERY MESSAGE BUTTON
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "set_delivery_message"
)
def handle_set_message_button(call):

    bot.answer_callback_query(call.id)

    admin_setting_message[ADMIN_ID] = True

    admin_adding_state.pop(
        ADMIN_ID,
        None
    )

    bot.send_message(

        ADMIN_ID,

        "📩 *Set Customer Delivery Message*\n\n"

        "Send me the exact message you want "
        "customers to receive after you approve "
        "their payment.\n\n"

        "You can send text, photo, video, "
        "document, audio, or animation.\n\n"

        "Use /setmessage anytime to replace it.",

        parse_mode="Markdown"
    )


# ============================================================
# SAVE DELIVERY MESSAGE
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.from_user.id == ADMIN_ID
        and admin_setting_message.get(
            ADMIN_ID,
            False
        ),
    content_types=[
        "text",
        "photo",
        "video",
        "document",
        "audio",
        "animation"
    ]
)
def save_delivery_message(message):

    try:

        # Stop waiting
        admin_setting_message.pop(
            ADMIN_ID,
            None
        )

        # Save the original message reference
        settings_col.update_one(

            {
                "setting": "delivery_message"
            },

            {
                "$set": {

                    "chat_id": message.chat.id,

                    "message_id": message.message_id,

                    "updated_at": datetime.utcnow()

                }
            },

            upsert=True
        )

        bot.send_message(

            ADMIN_ID,

            "✅ *Customer Delivery Message Saved!*\n\n"

            "This exact message will be copied to "
            "customers after you approve their payment.\n\n"

            "You can replace it anytime using:\n"
            "`/setmessage`",

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Error saving delivery message: {e}"
        )

        bot.send_message(

            ADMIN_ID,

            f"❌ Could not save the message.\n\n"
            f"Error:\n`{str(e)}`",

            parse_mode="Markdown"
        )


# ============================================================
# HANDLE FORWARDED CHANNEL MESSAGE
# ============================================================

@bot.message_handler(
    func=lambda m:
        m.from_user.id == ADMIN_ID
        and admin_adding_state.get(
            ADMIN_ID,
            False
        ),
    content_types=[
        "text",
        "photo",
        "video",
        "document",
        "audio",
        "animation"
    ]
)
def handle_forwarded_message(message):

    try:

        admin_adding_state.pop(
            ADMIN_ID,
            None
        )

        # Try to identify the channel
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

                "❌ *Could not detect the channel.*\n\n"

                "Please use `/add` and forward a message "
                "*directly from your Telegram channel*.",

                parse_mode="Markdown"
            )

            return

        if chat_obj.type not in [
            "channel",
            "supergroup"
        ]:

            bot.send_message(
                ADMIN_ID,
                "❌ The forwarded message does not "
                "appear to be from a supported channel."
            )

            return

        channel_id = chat_obj.id

        channel_name = (
            chat_obj.title
            or "Premium Channel"
        )

        # Save channel information
        channels_col.update_one(

            {
                "channel_id": channel_id
            },

            {
                "$set": {

                    "name": channel_name,

                    "price": FIXED_PRICE,

                    "membership": MEMBERSHIP_TYPE,

                    "admin_id": ADMIN_ID,

                    "updated_at": datetime.utcnow()

                }
            },

            upsert=True
        )

        # Generate customer bot link
        bot_username = bot.get_me().username

        customer_link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start={channel_id}"
        )

        bot.send_message(

            ADMIN_ID,

            f"✅ *Channel Setup Successful!*\n\n"

            f"📢 Channel: *{channel_name}*\n"
            f"💎 Membership: *{MEMBERSHIP_TYPE}*\n"
            f"💰 Price: *₹{FIXED_PRICE}*\n\n"

            f"🔗 *Customer Payment Link:*\n"
            f"`{customer_link}`\n\n"

            f"Give this link to your customers.",

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Channel setup error: {e}"
        )

        bot.send_message(

            ADMIN_ID,

            f"❌ *System Error*\n\n"
            f"`{str(e)}`",

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

        channel_id = int(
            call.data.split("_")[1]
        )

        channel_data = channels_col.find_one({

            "channel_id": channel_id

        })

        if not channel_data:

            bot.send_message(
                call.message.chat.id,
                "❌ Channel information not found."
            )

            return

        # ====================================================
        # CREATE UPI PAYMENT STRING
        # ====================================================

        upi_string = (
            f"upi://pay?"
            f"pa={quote(UPI_ID)}"
            f"&am={FIXED_PRICE}"
            f"&cu=INR"
        )

        qr_url = (
            "https://api.qrserver.com/v1/create-qr-code/"
            f"?size=400x400"
            f"&data={quote(upi_string)}"
        )

        markup = InlineKeyboardMarkup()

        markup.add(
            InlineKeyboardButton(
                "✅ I Have Paid",
                callback_data=f"paid_{channel_id}"
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

                f"Scan the QR code and complete "
                f"the payment.\n\n"

                f"After completing the payment, "
                f"click *I Have Paid*."

            ),

            reply_markup=markup,

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Payment selection error: {e}"
        )


# ============================================================
# I HAVE PAID
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

        channel_id = int(
            call.data.split("_")[1]
        )

        user = call.from_user

        channel_data = channels_col.find_one({

            "channel_id": channel_id

        })

        channel_name = (

            channel_data.get(
                "name",
                "Premium Channel"
            )

            if channel_data

            else "Premium Channel"

        )

        # ====================================================
        # CHECK EXISTING PENDING PAYMENT
        # ====================================================

        existing_payment = payments_col.find_one({

            "user_id": user.id,

            "channel_id": channel_id,

            "status": "pending"

        })

        if existing_payment:

            bot.send_message(

                call.message.chat.id,

                "⏳ *Payment Already Submitted*\n\n"

                "You already have a payment request "
                "waiting for admin verification.\n\n"

                "Please wait for approval.",

                parse_mode="Markdown"
            )

            return

        # ====================================================
        # CREATE PAYMENT RECORD
        # ====================================================

        payment_data = {

            "user_id": user.id,

            "username": user.username,

            "first_name": user.first_name,

            "channel_id": channel_id,

            "channel_name": channel_name,

            "amount": FIXED_PRICE,

            "membership": MEMBERSHIP_TYPE,

            "status": "pending",

            "created_at": datetime.utcnow()

        }

        result = payments_col.insert_one(
            payment_data
        )

        payment_id = str(
            result.inserted_id
        )

        # ====================================================
        # ADMIN APPROVAL BUTTONS
        # ====================================================

        markup = InlineKeyboardMarkup()

        markup.row(

            InlineKeyboardButton(
                "✅ APPROVE",
                callback_data=(
                    f"app_{user.id}_{channel_id}_{payment_id}"
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

            f"🔔 *PAYMENT VERIFICATION REQUIRED*\n\n"

            f"👤 User: *{user.first_name}*\n"
            f"📱 Username: {username_display}\n"
            f"🆔 User ID: `{user.id}`\n\n"

            f"📢 Channel: *{channel_name}*\n"
            f"💎 Membership: *{MEMBERSHIP_TYPE}*\n"
            f"💰 Amount: *₹{FIXED_PRICE}*\n\n"

            f"🆔 Payment ID:\n"
            f"`{payment_id}`\n\n"

            f"⚠️ Please verify the ₹{FIXED_PRICE} "
            f"payment in your UPI/bank account "
            f"before approving.",

            reply_markup=markup,

            parse_mode="Markdown"
        )

        # ====================================================
        # INFORM CUSTOMER
        # ====================================================

        bot.send_message(

            call.message.chat.id,

            "✅ *Payment Request Submitted!*\n\n"

            "Your payment is now waiting for "
            "manual verification by the administrator.\n\n"

            "You will receive the membership "
            "message after approval.",

            reply_markup=contact_admin_button(),

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

            bot.answer_callback_query(
                call.id,
                "This payment was already processed.",
                show_alert=True
            )

            return

        # Update database
        payments_col.update_one(

            {
                "_id": ObjectId(payment_id)
            },

            {
                "$set": {

                    "status": "rejected",

                    "rejected_at": datetime.utcnow(),

                    "rejected_by": ADMIN_ID

                }
            }
        )

        # Notify customer
        bot.send_message(

            user_id,

            "❌ *Payment Not Approved*\n\n"

            "Your payment could not be verified.\n\n"

            "If you have completed the payment, "
            "please contact the administrator.",

            reply_markup=contact_admin_button(),

            parse_mode="Markdown"
        )

        # Update admin message
        bot.edit_message_text(

            f"❌ *PAYMENT REJECTED*\n\n"

            f"👤 User ID: `{user_id}`\n"
            f"💰 Amount: ₹{FIXED_PRICE}\n"
            f"💎 Membership: {MEMBERSHIP_TYPE}\n\n"
            f"Payment ID:\n`{payment_id}`",

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

        channel_id = int(parts[2])

        payment_id = parts[3]

        # ====================================================
        # FIND PAYMENT
        # ====================================================

        payment = payments_col.find_one({

            "_id": ObjectId(payment_id)

        })

        if not payment:

            bot.send_message(
                ADMIN_ID,
                "❌ Payment record not found."
            )

            return

        # ====================================================
        # PREVENT DOUBLE APPROVAL
        # ====================================================

        if payment.get("status") != "pending":

            bot.answer_callback_query(

                call.id,

                "This payment has already been processed.",

                show_alert=True

            )

            return

        # ====================================================
        # CHECK DELIVERY MESSAGE
        # ====================================================

        delivery_message = get_delivery_message()

        if not delivery_message:

            bot.send_message(

                ADMIN_ID,

                "⚠️ *Cannot approve this payment yet.*\n\n"

                "You have not configured a customer "
                "delivery message.\n\n"

                "Use:\n"
                "`/setmessage`\n\n"

                "Then send the message you want "
                "customers to receive after payment.",

                parse_mode="Markdown"
            )

            bot.answer_callback_query(

                call.id,

                "Set the delivery message first.",

                show_alert=True

            )

            return

        # ====================================================
        # MARK PAYMENT AS APPROVED
        # ====================================================

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

        # ====================================================
        # SAVE USER MEMBERSHIP
        # ====================================================

        users_col.update_one(

            {

                "user_id": user_id,

                "channel_id": channel_id

            },

            {

                "$set": {

                    "user_id": user_id,

                    "channel_id": channel_id,

                    "membership": MEMBERSHIP_TYPE,

                    "status": "active",

                    "payment_id": payment_id,

                    "approved_at": datetime.utcnow()

                }

            },

            upsert=True

        )

        # ====================================================
        # COPY ADMIN'S SAVED MESSAGE
        # ====================================================

        bot.copy_message(

            chat_id=user_id,

            from_chat_id=delivery_message["chat_id"],

            message_id=delivery_message["message_id"]

        )

        # ====================================================
        # ADMIN CONFIRMATION
        # ====================================================

        bot.edit_message_text(

            f"✅ *PAYMENT APPROVED*\n\n"

            f"👤 User ID: `{user_id}`\n"
            f"💰 Amount: ₹{FIXED_PRICE}\n"
            f"💎 Membership: {MEMBERSHIP_TYPE}\n\n"

            f"📩 Your saved customer message "
            f"has been delivered successfully.\n\n"

            f"Payment ID:\n"
            f"`{payment_id}`",

            call.message.chat.id,

            call.message.message_id,

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Approval error: {e}"
        )

        # If something goes wrong, tell admin
        bot.send_message(

            ADMIN_ID,

            f"❌ *Approval/Delivery Error*\n\n"
            f"Payment ID:\n`{payment_id if 'payment_id' in locals() else 'Unknown'}`\n\n"
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

        bot.answer_callback_query(
            call.id
        )

        channel_id = int(
            call.data.split("_")[1]
        )

        channel_data = channels_col.find_one({

            "channel_id": channel_id

        })

        if not channel_data:

            bot.send_message(
                ADMIN_ID,
                "❌ Channel not found."
            )

            return

        bot_username = bot.get_me().username

        customer_link = (

            f"https://t.me/"
            f"{bot_username}"
            f"?start={channel_id}"

        )

        channel_name = channel_data.get(
            "name",
            "Premium Channel"
        )

        bot.edit_message_text(

            f"📢 *Channel Settings*\n\n"

            f"Channel: *{channel_name}*\n"
            f"💎 Membership: *{MEMBERSHIP_TYPE}*\n"
            f"💰 Price: *₹{FIXED_PRICE}*\n\n"

            f"🔗 *Customer Payment Link:*\n"
            f"`{customer_link}`",

            call.message.chat.id,

            call.message.message_id,

            parse_mode="Markdown"
        )

    except Exception as e:

        logging.error(
            f"Manage channel error: {e}"
        )


# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":

    # Start Render web server
    keep_alive()

    # Remove any previous webhook
    try:

        bot.remove_webhook()

    except Exception as e:

        logging.warning(
            f"Webhook cleanup note: {e}"
        )

    logging.info(
        "======================================"
    )

    logging.info(
        "Lifetime Membership Bot Started"
    )

    logging.info(
        f"Fixed Price: ₹{FIXED_PRICE}"
    )

    logging.info(
        f"Membership: {MEMBERSHIP_TYPE}"
    )

    logging.info(
        "======================================"
    )

    # Start Telegram polling
    bot.infinity_polling(

        timeout=20,

        long_polling_timeout=10,

        skip_pending=True

                )

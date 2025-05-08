import os
import logging
import random
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest
from aiohttp import web

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('airtime_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot configuration from environment variables
CONFIG = {
    'token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
    'admin_id': int(os.getenv('ADMIN_ID', '')),
    'required_channels': os.getenv('REQUIRED_CHANNELS', 'Freeinternetonly,Freeairtimehub,Freenethubchannel').split(','),
    'channel_links': os.getenv('CHANNEL_LINKS', 'https://t.me/Freeinternetonly,https://t.me/Freeairtimehub,https://t.me/Freenethubchannel').split(',')
}

# MongoDB connection
try:
    mongodb_uri = os.getenv('MONGODB_URI')
    if not mongodb_uri:
        raise ValueError("MONGODB_URI environment variable not set")
    
    # Add retryWrites and SSL parameters if not already in URI
    if "retryWrites" not in mongodb_uri:
        if "?" in mongodb_uri:
            mongodb_uri += "&retryWrites=true&w=majority"
        else:
            mongodb_uri += "?retryWrites=true&w=majority"
    
    # Force SSL/TLS connection
    if "ssl=true" not in mongodb_uri.lower():
        if "?" in mongodb_uri:
            mongodb_uri += "&ssl=true"
        else:
            mongodb_uri += "?ssl=true"
    
    client = MongoClient(
        mongodb_uri,
        tls=True,
        tlsAllowInvalidCertificates=False,
        connectTimeoutMS=30000,
        socketTimeoutMS=30000,
        serverSelectionTimeoutMS=30000
    )
    
    # Test the connection immediately
    client.admin.command('ping')
    logger.info("Successfully connected to MongoDB")
    
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    raise

db = client[os.getenv('DATABASE_NAME', '')]

# Collections
users_collection = db['users']
referral_history_collection = db['referral_history']
feedback_collection = db['feedback']
milestone_rewards_collection = db['milestone_rewards']
transactions_collection = db['transactions']

# Webhook configuration
PORT = int(os.getenv('PORT', 10000))
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '') + WEBHOOK_PATH

# === DATABASE FUNCTIONS ===
def add_user(user, referrer_id=None):
    """Add user to database if not exists"""
    user_data = {
        'user_id': user.id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'credits': 0,
        'banned': False,
        'referral_link_expiry': None,
        'tier': None,
        'last_active': datetime.now().isoformat(),
        'join_date': datetime.now().isoformat()
    }
    
    if referrer_id:
        user_data['referrer_id'] = referrer_id
    
    users_collection.update_one(
        {'user_id': user.id},
        {'$setOnInsert': user_data},
        upsert=True
    )

def add_referral(referrer_id, referred_id):
    """Add a referral record"""
    referral_history_collection.insert_one({
        'referrer_id': referrer_id,
        'referred_id': referred_id,
        'timestamp': datetime.now().isoformat()
    })

def add_feedback(user_id, message):
    """Add feedback to database"""
    feedback_collection.insert_one({
        'user_id': user_id,
        'message': message,
        'timestamp': datetime.now().isoformat()
    })

def add_milestone_reward(user_id, milestone, reward):
    """Add milestone reward to database"""
    milestone_rewards_collection.insert_one({
        'user_id': user_id,
        'milestone': milestone,
        'reward': reward,
        'timestamp': datetime.now().isoformat()
    })

def add_transaction(user_id, transaction_type, amount, status='completed'):
    """Add a transaction record"""
    transactions_collection.insert_one({
        'user_id': user_id,
        'type': transaction_type,
        'amount': amount,
        'status': status,
        'timestamp': datetime.now().isoformat()
    })

def update_user_credits(user_id, amount):
    """Update user's credits"""
    users_collection.update_one(
        {'user_id': user_id},
        {'$inc': {'credits': amount}}
    )

def get_user(user_id):
    """Get user data"""
    return users_collection.find_one({'user_id': user_id})

def get_user_credits(user_id):
    """Get user's credits"""
    user = get_user(user_id)
    return user['credits'] if user else 0

def get_referral_count(user_id):
    """Get number of referrals for a user"""
    return referral_history_collection.count_documents({'referrer_id': user_id})

def get_top_referrers(limit=10):
    """Get top referrers"""
    pipeline = [
        {"$group": {"_id": "$referrer_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit}
    ]
    return list(referral_history_collection.aggregate(pipeline))

def get_banned_users():
    """Get list of banned users"""
    return list(users_collection.find({'banned': True}, {'user_id': 1}))

def reset_all_credits():
    """Reset all users' credits to zero"""
    users_collection.update_many({}, {'$set': {'credits': 0}})

def update_user_tier(user_id, tier):
    """Update user's tier"""
    users_collection.update_one(
        {'user_id': user_id},
        {'$set': {'tier': tier}}
    )

def update_user_activity(user_id):
    """Update user's last active time"""
    users_collection.update_one(
        {'user_id': user_id},
        {'$set': {'last_active': datetime.now().isoformat()}}
    )

def update_referral_link_expiry(user_id, expiry_time):
    """Update referral link expiry time"""
    users_collection.update_one(
        {'user_id': user_id},
        {'$set': {'referral_link_expiry': expiry_time.isoformat()}}
    )

def ban_user(user_id):
    """Ban a user"""
    users_collection.update_one(
        {'user_id': user_id},
        {'$set': {'banned': True}}
    )

def unban_user(user_id):
    """Unban a user"""
    users_collection.update_one(
        {'user_id': user_id},
        {'$set': {'banned': False}}
    )

# === FORCE JOIN FUNCTIONALITY ===
async def is_user_member(user_id, bot):
    """Check if user is member of all required channels"""
    for channel in CONFIG['required_channels']:
        try:
            chat_member = await bot.get_chat_member(chat_id=f"@{channel}", user_id=user_id)
            if chat_member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logger.error(f"Error checking membership for {user_id} in {channel}: {e}")
            return False
    return True

async def ask_user_to_join(update):
    """Send message with join buttons"""
    buttons = [
        [InlineKeyboardButton(f"Join {CONFIG['required_channels'][i]}", url=CONFIG['channel_links'][i])] 
        for i in range(len(CONFIG['required_channels']))
    ]
    buttons.append([InlineKeyboardButton("✅ I Joined", callback_data="verify_membership")])
    
    await update.message.reply_text(
        "🚨 *To use this bot, you must join the required channels first!* 🚨\n\n"
        "Click the buttons below to join, then press *'✅ I Joined'*.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle membership verification"""
    query = update.callback_query
    user_id = query.from_user.id

    if await is_user_member(user_id, context.bot):
        await query.message.edit_text("✅ You are verified! You can now refer others and earn UGX.")
        await start(update, context)
    else:
        await query.answer("❌ You haven't joined all the required channels yet!", show_alert=True)

# === COMMAND HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    user_id = user.id

    # Check if user has joined all required channels
    if not await is_user_member(user_id, context.bot):
        await ask_user_to_join(update)
        return

    # Check if user was referred
    referrer_id = None
    if context.args:
        try:
            referrer_id = int(context.args[0])
            # Ensure the referrer exists and is not the same as the user
            if referrer_id == user_id or not users_collection.find_one({'user_id': referrer_id}):
                referrer_id = None
        except ValueError:
            referrer_id = None

    # Add user to database
    add_user(user, referrer_id)

    if referrer_id:
        # Add referral record
        add_referral(referrer_id, user_id)
        
        # Reward referrer with 10 UGX
        update_user_credits(referrer_id, 10)
        add_transaction(referrer_id, "referral_bonus", 10)
        
        # Notify referrer
        try:
            referred_username = user.username or f"User {user_id}"
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"🎉 You have successfully referred {referred_username}! You earned **10 UGX**.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify referrer {referrer_id}: {e}")

    # Generate referral link
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"

    keyboard = [[InlineKeyboardButton("Invite Friends", url=referral_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"✅ Welcome! Share this link to refer others:\n{referral_link}\n\n"
        "Earn **10 UGX** for each referral!",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /credits command"""
    user_id = update.effective_user.id
    credits = get_user_credits(user_id)
    await update.message.reply_text(f"💰 You currently have **{credits} UGX**.", parse_mode="Markdown")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /withdraw command"""
    user_id = update.effective_user.id
    credits = get_user_credits(user_id)

    if credits >= 500:
        # Deduct 500 UGX
        update_user_credits(user_id, -500)
        add_transaction(user_id, "withdrawal", 500, "pending")
        
        # Notify admin
        try:
            await context.bot.send_message(
                chat_id=CONFIG['admin_id'],
                text=f"🚨 Withdrawal Request:\nUser ID: {user_id}\nAmount: 500 UGX"
            )
            await update.message.reply_text("✅ Your withdrawal request for 500 UGX has been submitted. The admin will process it shortly.")
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
            await update.message.reply_text("❌ Failed to process your withdrawal request. Please try again later.")
    else:
        await update.message.reply_text("❌ You need at least 500 UGX to withdraw.")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /leaderboard command"""
    top_referrers = get_top_referrers()
    
    if not top_referrers:
        await update.message.reply_text("❌ No data available for the leaderboard.")
        return

    leaderboard_text = "🏆 **Top Referrers:**\n\n"
    for i, item in enumerate(top_referrers, start=1):
        user_id = item['_id']
        count = item['count']
        user = get_user(user_id)
        username = user.get('username', f"User {user_id}") if user else f"User {user_id}"
        leaderboard_text += f"{i}. {username}: {count} referrals\n"

    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /redeem command"""
    user_id = update.effective_user.id
    credits = get_user_credits(user_id)

    if credits >= 50:
        update_user_credits(user_id, -50)
        add_transaction(user_id, "redemption", 50)
        await update.message.reply_text("🎉 You have successfully redeemed 50 UGX for rewards!")
    else:
        await update.message.reply_text("❌ You need at least 50 UGX to redeem rewards.")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /profile command"""
    user = update.effective_user
    user_id = user.id
    user_data = get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ You are not registered in the system. Use /start to register.")
        return

    profile_text = f"""
📝 **Your Profile:**
- User ID: {user_id}
- UGX: {user_data.get('credits', 0)}
- Referrer ID: {user_data.get('referrer_id', 'None')}
- Referrals: {get_referral_count(user_id)}
- Tier: {user_data.get('tier', 'None')}
    """
    await update.message.reply_text(profile_text, parse_mode="Markdown")

async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /referrals command"""
    user_id = update.effective_user.id
    referral_count = get_referral_count(user_id)
    await update.message.reply_text(f"📊 You have referred **{referral_count} users**.", parse_mode="Markdown")

async def referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /referrallink command"""
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    await update.message.reply_text(
        f"🔗 Your referral link:\n{referral_link}\n\n"
        "Share this link to refer others and earn **10 UGX** for each successful referral!",
        parse_mode="Markdown"
    )

async def contact_us(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /contactus command"""
    contact_text = """
☎️ YOU CAN WRITE TO ME BY USING MY TELEGRAM NAME 

🔖 NAME TAG:
@SILANDO

❗ ONLY FOR BUSINESS AND HELP, DON'T SPAM!
    """
    await update.message.reply_text(contact_text)

async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /feedback command"""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Please provide your feedback.")
        return

    message = " ".join(context.args)
    add_feedback(user_id, message)
    await update.message.reply_text("✅ Thank you for your feedback!")

# === ADMIN COMMANDS ===
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /broadcast command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    if not context.args:
        await update.message.reply_text("❌ Please provide a message to broadcast.")
        return

    message = " ".join(context.args)
    users = users_collection.find({}, {'user_id': 1})
    success = 0

    for user in users:
        try:
            await context.bot.send_message(chat_id=user['user_id'], text=message)
            success += 1
        except Exception as e:
            logger.error(f"Failed to send message to user {user['user_id']}: {e}")

    await update.message.reply_text(f"✅ Broadcast sent to {success} users.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    total_users = users_collection.count_documents({})
    total_credits = users_collection.aggregate([{
        "$group": {
            "_id": None,
            "total": {"$sum": "$credits"}
        }
    }]).next().get('total', 0)

    stats_text = f"""
📊 **Bot Statistics:**
- Total Users: {total_users}
- Total UGX: {total_credits}
    """
    await update.message.reply_text(stats_text, parse_mode="Markdown")

async def add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addcredits command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /addcredits <user_id> <credits>")
        return

    target_user_id = int(context.args[0])
    credits_to_add = int(context.args[1])

    update_user_credits(target_user_id, credits_to_add)
    add_transaction(target_user_id, "admin_add", credits_to_add)
    await update.message.reply_text(f"✅ Added {credits_to_add} UGX to user {target_user_id}.")

async def remove_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /removecredits command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /removecredits <user_id> <credits>")
        return

    target_user_id = int(context.args[0])
    credits_to_remove = int(context.args[1])

    update_user_credits(target_user_id, -credits_to_remove)
    add_transaction(target_user_id, "admin_remove", credits_to_remove)
    await update.message.reply_text(f"✅ Removed {credits_to_remove} UGX from user {target_user_id}.")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ban command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: /ban <user_id>")
        return

    target_user_id = int(context.args[0])
    ban_user(target_user_id)
    await update.message.reply_text(f"✅ User {target_user_id} has been banned.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unban command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: /unban <user_id>")
        return

    target_user_id = int(context.args[0])
    unban_user(target_user_id)
    await update.message.reply_text(f"✅ User {target_user_id} has been unbanned.")

async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sendmessage command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /sendmessage <user_id> <message>")
        return

    target_user_id = int(context.args[0])
    message = " ".join(context.args[1:])

    try:
        await context.bot.send_message(chat_id=target_user_id, text=message)
        await update.message.reply_text(f"✅ Message sent to user {target_user_id}.")
    except Exception as e:
        logger.error(f"Failed to send message to user {target_user_id}: {e}")
        await update.message.reply_text(f"❌ Failed to send message to user {target_user_id}.")

async def list_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /listbanned command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    banned_users = get_banned_users()
    if banned_users:
        banned_users_text = "🚫 **Banned Users:**\n\n"
        for user in banned_users:
            banned_users_text += f"- User {user['user_id']}\n"

        await update.message.reply_text(banned_users_text, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ No users are currently banned.")

async def reset_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resetleaderboard command"""
    if update.effective_user.id != CONFIG['admin_id']:
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return

    reset_all_credits()
    await update.message.reply_text("✅ Leaderboard has been reset.")

async def contest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /contest command"""
    pipeline = [
        {"$group": {"_id": "$referrer_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 1}
    ]
    top_referrer = next(referral_history_collection.aggregate(pipeline), None)

    if top_referrer:
        top_referrer_id = top_referrer['_id']
        referrals_count = top_referrer['count']
        if referrals_count >= 100:
            update_user_credits(top_referrer_id, 500)
            add_transaction(top_referrer_id, "contest_reward", 500)
            await update.message.reply_text(
                f"🎉 User {top_referrer_id} has won the referral contest with {referrals_count} referrals and earned **500 UGX**!",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🏆 The current top referrer has {referrals_count} referrals. The first user to reach 100 referrals will win **500 UGX**!",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text("❌ No referrals have been made yet.")

# === UTILITY FUNCTIONS ===
async def generate_referral_link(user_id, context):
    """Generate referral link with expiry"""
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    expiry_time = datetime.now() + timedelta(hours=48)
    update_referral_link_expiry(user_id, expiry_time)
    return referral_link

async def notify_referral_link_expiry(user_id, context):
    """Notify user about expiring referral link"""
    user = get_user(user_id)
    if user and user.get('referral_link_expiry'):
        expiry_time = datetime.fromisoformat(user['referral_link_expiry'])
        if (expiry_time - datetime.now()).total_seconds() <= 3600:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ Your referral link is about to expire in 1 hour. Generate a new one using /referrallink."
            )

async def update_tier(user_id):
    """Update user's tier based on referrals"""
    referral_count = get_referral_count(user_id)
    if referral_count >= 200:
        tier = "Gold"
    elif referral_count >= 100:
        tier = "Silver"
    elif referral_count >= 50:
        tier = "Bronze"
    else:
        tier = None

    if tier:
        update_user_tier(user_id, tier)

async def track_user_activity(user_id, context):
    """Track user activity and send reminder if inactive"""
    update_user_activity(user_id)
    user = get_user(user_id)
    if user and user.get('last_active'):
        last_active = datetime.fromisoformat(user['last_active'])
        if (datetime.now() - last_active).days >= 3:
            await context.bot.send_message(
                chat_id=user_id,
                text="👋 You haven't been active for 3 days. Come back and earn more UGX!"
            )

async def check_milestone_rewards(user_id, context):
    """Check and reward referral milestones"""
    referral_count = get_referral_count(user_id)
    if referral_count >= 500:
        update_user_credits(user_id, 1000)
        add_transaction(user_id, "milestone_reward", 1000)
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 You have reached 500 referrals and earned **1000 UGX**!",
            parse_mode="Markdown"
        )

# === WEBHOOK SETUP ===
async def health_check(request):
    """Health check endpoint"""
    return web.Response(text="OK")

async def telegram_webhook(request):
    """Handle incoming webhook requests"""
    update = Update.de_json(await request.json(), application.bot)
    await application.update_queue.put(update)
    return web.Response(text="OK")

def main():
    """Run the bot"""
    global application
    application = Application.builder().token(CONFIG['token']).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("credits", credits))
    application.add_handler(CommandHandler("withdraw", withdraw))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("redeem", redeem))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("referrals", referrals))
    application.add_handler(CommandHandler("referrallink", referral_link))
    application.add_handler(CommandHandler("contactus", contact_us))
    application.add_handler(CommandHandler("feedback", feedback))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("addcredits", add_credits))
    application.add_handler(CommandHandler("removecredits", remove_credits))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("sendmessage", send_message))
    application.add_handler(CommandHandler("listbanned", list_banned))
    application.add_handler(CommandHandler("resetleaderboard", reset_leaderboard))
    application.add_handler(CommandHandler("contest", contest))
    application.add_handler(CallbackQueryHandler(verify_membership, pattern="^verify_membership$"))

    # Start the bot with webhook if running on Render
    if os.getenv('RENDER'):
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=WEBHOOK_URL
        )
    else:
        application.run_polling()

if __name__ == "__main__":
    main()

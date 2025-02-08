from telegram.ext import CallbackQueryHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
import sqlite3
import logging
from datetime import datetime, timedelta

# Enable logging to the console
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]  # Output logs to the console
)
logger = logging.getLogger(__name__)

# === BOT CONFIGURATION ===
TOKEN = "8175054975:AAHYcmNI8TJttEu8Rtq_HYwRjntjEXqcQ2s"  # Replace with your bot token
ADMIN_ID = 6211392720  # Replace with your admin ID

# Required channels (replace with your actual channel usernames)
REQUIRED_CHANNELS = ["Freeinternetonly","Freeairtimehub", "Freenethubchannel"]  # Channel usernames without "@"

# === Database Setup ===
conn = sqlite3.connect("referrals.db", check_same_thread=False)
cursor = conn.cursor()

# Create users table with credits
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        referrer_id INTEGER,
        credits INTEGER DEFAULT 0,
        banned BOOLEAN DEFAULT FALSE,
        referral_link_expiry TEXT,  -- For referral link expiry
        tier TEXT,  -- For referral tier system
        last_active TEXT  -- For user activity tracker
    )
""")

# Create referral history table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS referral_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER,
        timestamp TEXT
    )
""")

# Create feedback table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        timestamp TEXT
    )
""")

# Create milestone rewards table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS milestone_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        milestone INTEGER,
        reward INTEGER,
        timestamp TEXT
    )
""")
conn.commit()

# === Function to Check Membership ===
async def is_user_member(user_id, bot):
    for channel in REQUIRED_CHANNELS:
        try:
            chat_member = await bot.get_chat_member(chat_id=f"@{channel}", user_id=user_id)
            if chat_member.status not in ["member", "administrator", "creator"]:
                return False  # User is NOT a member
        except:
            return False  # If error occurs, assume not a member
    return True  # User is a member of all channels

# === Function to Show Join Buttons ===
async def ask_user_to_join(update):
    # Define custom button labels and their corresponding channel links
    channel_buttons = [
        {"label": "MAIN CHANNEL", "url": "https://t.me/Freeinternetonly"}, 
        {"label": "CHANNEL ANNOUNCEMENT", "url": "https://t.me/Freeairtimehub"},
        {"label": "BACKUP CHANNEL", "url": "https://t.me/Freenethubchannel"},
    ]

    # Create buttons with custom labels
    buttons = [[InlineKeyboardButton(button["label"], url=button["url"])] for button in channel_buttons]
    buttons.append([InlineKeyboardButton("✅ I Joined", callback_data="verify_membership")])
    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        "🚨 *To use this bot, you must join the required channels first!* 🚨\n\n"
        "Click the buttons below to join, then press *'✅ I Joined'*.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# === Start Command (Checks Membership First) ===
async def start(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if user has joined all required channels before showing anything else
    if not await is_user_member(user_id, context.bot):
        await ask_user_to_join(update)
        return  # Stop execution until user verifies

    # If user has joined, continue with referral system
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()

    if user_data is None:
        # Check if the user was referred by someone
        if context.args:
            referrer_id = int(context.args[0])
            # Insert the new user into the database with the referrer_id
            cursor.execute("INSERT INTO users (user_id, referrer_id, credits) VALUES (?, ?, 0)", (user_id, referrer_id))
            conn.commit()

            # Reward the referrer with 10 UGX
            cursor.execute("UPDATE users SET credits = credits + 10 WHERE user_id=?", (referrer_id,))
            conn.commit()

            # Notify the referrer with the referred user's username
            try:
                referred_user = await context.bot.get_chat(user_id)
                referred_username = referred_user.username if referred_user.username else f"User {user_id}"
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎉 You have successfully referred {referred_username}! You earned **10 UGX**."
                )
            except Exception as e:
                logger.error(f"Failed to notify referrer {referrer_id}: {e}")
        else:
            # If the user was not referred, insert them into the database without a referrer_id
            cursor.execute("INSERT INTO users (user_id, credits) VALUES (?, 0)", (user_id,))
            conn.commit()

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

# === Verify Membership Button Handler ===
async def verify_membership(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    if await is_user_member(user_id, context.bot):
        await query.message.edit_text("✅ You are verified! You can now refer others and earn UGX.")
        # Restart the bot for the user to access the referral system
        await start(update, context)
    else:
        await query.answer("❌ You haven't joined all the required channels yet!", show_alert=True)

# === Credits Command ===
async def credits(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Fetch user's credits from the database
    cursor.execute("SELECT credits FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        credits = user_data[0]
        await update.message.reply_text(f"💰 You currently have **{credits} UGX**.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ You are not registered in the system. Use /start to register.")

# === Withdraw Command ===
async def withdraw(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Fetch user's credits from the database
    cursor.execute("SELECT credits FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        credits = user_data[0]
        if credits >= 500:
            # Deduct 500 UGX and notify admin
            cursor.execute("UPDATE users SET credits = credits - 500 WHERE user_id=?", (user_id,))
            conn.commit()

            # Notify admin
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"🚨 Withdrawal Request:\nUser ID: {user_id}\nAmount: 500 UGX"
                )
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")

            await update.message.reply_text("✅ Your withdrawal request for 500 UGX has been submitted. The admin will process it shortly.")
        else:
            await update.message.reply_text("❌ You need at least 500 UGX to withdraw.")
    else:
        await update.message.reply_text("❌ You are not registered in the system. Use /start to register.")

# === Leaderboard Command ===
async def leaderboard(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Fetch top referrers from the database
    cursor.execute("""
        SELECT user_id, credits 
        FROM users 
        ORDER BY credits DESC 
        LIMIT 10
    """)
    top_referrers = cursor.fetchall()

    if top_referrers:
        leaderboard_text = "🏆 **Top Referrers:**\n\n"
        for i, (user_id, credits) in enumerate(top_referrers, start=1):
            leaderboard_text += f"{i}. User {user_id}: {credits} UGX\n"

        await update.message.reply_text(leaderboard_text, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No data available for the leaderboard.")

# === Redeem Command ===
async def redeem(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Fetch user's credits from the database
    cursor.execute("SELECT credits FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        credits = user_data[0]
        if credits >= 50:
            # Deduct 50 UGX and provide rewards
            cursor.execute("UPDATE users SET credits = credits - 50 WHERE user_id=?", (user_id,))
            conn.commit()
            await update.message.reply_text("🎉 You have successfully redeemed 50 UGX for rewards!")
        else:
            await update.message.reply_text("❌ You need at least 50 UGX to redeem rewards.")
    else:
        await update.message.reply_text("❌ You are not registered in the system. Use /start to register.")

# === Broadcast Command (Admin Only) ===
async def broadcast(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Get the broadcast message from the command arguments
    if not context.args:
        await update.message.reply_text("❌ Please provide a message to broadcast.")
        return

    message = " ".join(context.args)

    # Fetch all user IDs from the database
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    # Send the broadcast message to all users
    for (user_id,) in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            logger.error(f"Failed to send message to user {user_id}: {e}")

    await update.message.reply_text("✅ Broadcast message sent to all users.")

# === Stats Command (Admin Only) ===
async def stats(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Fetch bot statistics from the database
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(credits) FROM users")
    total_credits = cursor.fetchone()[0] or 0

    stats_text = f"""
📊 **Bot Statistics:**
- Total Users: {total_users}
- Total UGX: {total_credits}
    """
    await update.message.reply_text(stats_text, parse_mode="Markdown")

# === Profile Command ===
async def profile(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Fetch user's profile from the database
    cursor.execute("SELECT credits, referrer_id FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        credits, referrer_id = user_data
        profile_text = f"""
📝 **Your Profile:**
- User ID: {user_id}
- UGX: {credits}
- Referrer ID: {referrer_id if referrer_id else "None"}
        """
        await update.message.reply_text(profile_text, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ You are not registered in the system. Use /start to register.")

# === Referrals Command ===
async def referrals(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Fetch the number of users referred by the current user
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
    referrals_count = cursor.fetchone()[0]

    await update.message.reply_text(f"📊 You have referred **{referrals_count} users**.", parse_mode="Markdown")

# === Add Credits Command (Admin Only) ===
async def add_credits(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Get the target user ID and credits to add
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /addcredits <user_id> <credits>")
        return

    target_user_id = int(context.args[0])
    credits_to_add = int(context.args[1])

    # Add credits to the target user's account
    cursor.execute("UPDATE users SET credits = credits + ? WHERE user_id=?", (credits_to_add, target_user_id))
    conn.commit()

    await update.message.reply_text(f"✅ Added {credits_to_add} UGX to user {target_user_id}.")

# === Remove Credits Command (Admin Only) ===
async def remove_credits(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Get the target user ID and credits to remove
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /removecredits <user_id> <credits>")
        return

    target_user_id = int(context.args[0])
    credits_to_remove = int(context.args[1])

    # Remove credits from the target user's account
    cursor.execute("UPDATE users SET credits = credits - ? WHERE user_id=?", (credits_to_remove, target_user_id))
    conn.commit()

    await update.message.reply_text(f"✅ Removed {credits_to_remove} UGX from user {target_user_id}.")

# === Ban Command (Admin Only) ===
async def ban(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Get the target user ID to ban
    if not context.args:
        await update.message.reply_text("❌ Usage: /ban <user_id>")
        return

    target_user_id = int(context.args[0])

    # Ban the target user
    cursor.execute("UPDATE users SET banned = TRUE WHERE user_id=?", (target_user_id,))
    conn.commit()

    await update.message.reply_text(f"✅ User {target_user_id} has been banned.")

# === Unban Command (Admin Only) ===
async def unban(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Get the target user ID to unban
    if not context.args:
        await update.message.reply_text("❌ Usage: /unban <user_id>")
        return

    target_user_id = int(context.args[0])

    # Unban the target user
    cursor.execute("UPDATE users SET banned = FALSE WHERE user_id=?", (target_user_id,))
    conn.commit()

    await update.message.reply_text(f"✅ User {target_user_id} has been unbanned.")

# === Referral Link Command ===
async def referral_link(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Generate referral link
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"

    await update.message.reply_text(
        f"🔗 Your referral link:\n{referral_link}\n\n"
        "Share this link to refer others and earn **10 UGX** for each successful referral!",
        parse_mode="Markdown"
    )

# === Contact Us Command ===
async def contact_us(update: Update, context: CallbackContext):
    contact_text = """
☎️ YOU CAN WRITE TO ME BY USING MY TELEGRAM NAME 

🔖 NAME TAG:
@SILANDO

❗ ONLY FOR BUSINESS AND HELP, DON'T SPAM!
    """
    await update.message.reply_text(contact_text)

# === New Features ===

# === Send Message Command (Admin Only) ===
async def send_message(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Get the target user ID and message
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

# === List Banned Users Command (Admin Only) ===
async def list_banned(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Fetch all banned users
    cursor.execute("SELECT user_id FROM users WHERE banned = TRUE")
    banned_users = cursor.fetchall()

    if banned_users:
        banned_users_text = "🚫 **Banned Users:**\n\n"
        for (user_id,) in banned_users:
            banned_users_text += f"- User {user_id}\n"

        await update.message.reply_text(banned_users_text, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ No users are currently banned.")

# === Reset Leaderboard Command (Admin Only) ===
async def reset_leaderboard(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Check if the user is an admin
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ You do not have permission to use this command.")
        return

    # Reset all users' credits to zero
    cursor.execute("UPDATE users SET credits = 0")
    conn.commit()

    await update.message.reply_text("✅ Leaderboard has been reset.")

# === Referral Contest Command ===
async def contest(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Fetch contest details
    cursor.execute("SELECT user_id, COUNT(*) FROM users WHERE referrer_id IS NOT NULL GROUP BY referrer_id ORDER BY COUNT(*) DESC LIMIT 1")
    top_referrer = cursor.fetchone()

    if top_referrer:
        top_referrer_id, referrals_count = top_referrer
        if referrals_count >= 100:
            # Reward the top referrer with 500 UGX
            cursor.execute("UPDATE users SET credits = credits + 500 WHERE user_id=?", (top_referrer_id,))
            conn.commit()

            await update.message.reply_text(f"🎉 User {top_referrer_id} has won the referral contest with {referrals_count} referrals and earned **500 UGX**!", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"🏆 The current top referrer has {referrals_count} referrals. The first user to reach 100 referrals will win **500 UGX**!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No referrals have been made yet.")

# === Feedback Command ===
async def feedback(update: Update, context: CallbackContext):
    user_id = update.message.chat.id

    # Get the feedback message
    if not context.args:
        await update.message.reply_text("❌ Please provide your feedback.")
        return

    message = " ".join(context.args)

    # Insert feedback into the database
    cursor.execute("INSERT INTO feedback (user_id, message, timestamp) VALUES (?, ?, ?)", (user_id, message, datetime.now().isoformat()))
    conn.commit()

    await update.message.reply_text("✅ Thank you for your feedback!")

# === Referral Link Expiry ===
async def generate_referral_link(user_id):
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"

    # Set referral link expiry to 48 hours from now
    expiry_time = (datetime.now() + timedelta(hours=48)).isoformat()
    cursor.execute("UPDATE users SET referral_link_expiry = ? WHERE user_id=?", (expiry_time, user_id))
    conn.commit()

    return referral_link
    
    # === Referral Link Expiry Notification ===
async def notify_referral_link_expiry(user_id):
    # Fetch referral link expiry time
    cursor.execute("SELECT referral_link_expiry FROM users WHERE user_id=?", (user_id,))
    expiry_time = cursor.fetchone()[0]

    if expiry_time and (datetime.fromisoformat(expiry_time) - datetime.now()).total_seconds() <= 3600:  # 1 hour before expiry
        await context.bot.send_message(chat_id=user_id, text="⚠️ Your referral link is about to expire in 1 hour. Generate a new one using /referrallink.")

# === Referral Tier System ===
async def update_tier(user_id):
    # Fetch the number of referrals
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
    referrals_count = cursor.fetchone()[0]

    # Update tier based on referrals count
    if referrals_count >= 200:
        tier = "Gold"
    elif referrals_count >= 100:
        tier = "Silver"
    elif referrals_count >= 50:
        tier = "Bronze"
    else:
        tier = None

    cursor.execute("UPDATE users SET tier = ? WHERE user_id=?", (tier, user_id))
    conn.commit()

# === User Activity Tracker ===
async def track_user_activity(user_id):
    # Update last active time
    cursor.execute("UPDATE users SET last_active = ? WHERE user_id=?", (datetime.now().isoformat(), user_id))
    conn.commit()

    # Check if the user has been inactive for 3 days
    cursor.execute("SELECT last_active FROM users WHERE user_id=?", (user_id,))
    last_active = cursor.fetchone()[0]

    if last_active and (datetime.now() - datetime.fromisoformat(last_active)).days >= 3:
        await context.bot.send_message(chat_id=user_id, text="👋 You haven't been active for 3 days. Come back and earn more UGX!")

# === Referral Milestone Rewards ===
async def check_milestone_rewards(user_id):
    # Fetch the number of referrals
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
    referrals_count = cursor.fetchone()[0]

    # Check if the user has reached a milestone
    if referrals_count >= 500:
        # Reward the user with 1000 UGX
        cursor.execute("UPDATE users SET credits = credits + 1000 WHERE user_id=?", (user_id,))
        conn.commit()

        await context.bot.send_message(chat_id=user_id, text="🎉 You have reached 500 referrals and earned **1000 UGX**!", parse_mode="Markdown")

# === Main Function ===
def main():
    app = Application.builder().token(TOKEN).read_timeout(30).write_timeout(30).build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("credits", credits))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("referrals", referrals))
    app.add_handler(CommandHandler("addcredits", add_credits))
    app.add_handler(CommandHandler("removecredits", remove_credits))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("referrallink", referral_link))
    app.add_handler(CommandHandler("contactus", contact_us))
    app.add_handler(CommandHandler("sendmessage", send_message))  # New command
    app.add_handler(CommandHandler("listbanned", list_banned))  # New command
    app.add_handler(CommandHandler("resetleaderboard", reset_leaderboard))  # New command
    app.add_handler(CommandHandler("contest", contest))  # New command
    app.add_handler(CommandHandler("feedback", feedback))  # New command
    app.add_handler(CallbackQueryHandler(verify_membership, pattern="^verify_membership$"))

    app.run_polling()

if __name__ == "__main__":
    main()


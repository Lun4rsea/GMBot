import json
import os
import sqlite3
import logging
import re
import dotenv
from dotenv import load_dotenv
from datetime import datetime, timedelta
from telegram import Update, Bot
from telegram.ext import CommandHandler, MessageHandler, filters, CallbackContext, Application


signature = """
                           .-') _          _  .-')   
                          ( OO ) )        ( \( -O )  
 ,--.     ,--. ,--.   ,--./ ,--,'   .---.  ,------.  
 |  |.-') |  | |  |   |   \ |  |\  / .  |  |   /`. ' 
 |  | OO )|  | | .-') |    \|  | )/ /|  |  |  /  | | 
 |  |`-' ||  |_|( OO )|  .     |// / |  |_ |  |_.' | 
(|  '---.'|  | | `-' /|  |\    |/  '-'    ||  .  '.' 
 |      |('  '-'(_.-' |  | \   |`----|  |-'|  |\  \  
 `------'  `-----'    `--'  `--'     `--'  `--' '--'  
"""

print(signature)


# Telegram Bot Token
TOKEN = os.getenv("TOKEN")

# Database setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "gm_bot.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def sanitize_table_name(group_id):
    """Convert group ID to a valid SQLite table name."""
    # Replace negative sign with 'n' prefix for negative IDs
    return f"group_{'n' if group_id < 0 else ''}{abs(group_id)}"

def ensure_group_table(group_id):
    """Ensure a separate table exists for each group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    table_name = sanitize_table_name(group_id)
    
    # Check if table exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name=?
    """, (table_name,))
    
    if not cursor.fetchone():
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                last_gm DATE,
                total_gm INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0
            )
        """)
        conn.commit()
    
    conn.close()
    return table_name

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def check_gm(message: str) -> bool:
    """Check if the message contains a good morning variant."""
    gm_variants = [r'\bGM\b', r'\bgood morning\b', r'\bgoodmorning\b', r'\bmorning\b']
    return any(re.search(variant, message, re.IGNORECASE) for variant in gm_variants)

async def start(update: Update, context: CallbackContext) -> None:
    """Handle the /start command and prompt users to add the bot to their server."""
    bot_username = context.bot.username
    invite_link = f"https://t.me/{bot_username}?startgroup=true"
    message = ("👋 Hello! I'm your Good Morning bot! ☀️\n"
               "I help track daily 'Good Mornings' and streaks. Add me to your group using the button below!\n\n"
               "[Add to Group](" + invite_link + ")")
    await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)

async def gm_leaderboard(update: Update, context: CallbackContext) -> None:
    """Show GM leaderboard for the specific group."""
    chat_id = update.message.chat_id
    table_name = ensure_group_table(chat_id)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT username, total_gm FROM {table_name} ORDER BY total_gm DESC")
        total_gm_leaderboard = cursor.fetchall()
        
        cursor.execute(f"SELECT username, streak FROM {table_name} ORDER BY streak DESC")
        streak_leaderboard = cursor.fetchall()
        
        message = "🏆 GM Leaderboards for This Group 🏆\n\n"
        message += "📊 Most GMs Sent:\n"
        for i, (username, total_gm) in enumerate(total_gm_leaderboard, 1):
            message += f"{i}. {username or 'Anonymous'} - {total_gm} GMs\n"
        
        message += "\n🔥 Longest Current Streaks:\n"
        for i, (username, streak) in enumerate(streak_leaderboard, 1):
            message += f"{i}. {username or 'Anonymous'} - {streak} days\n"
        
        message += "\n[Get early access to AXIOM today!](https://axiom.trade/@lun4r)"
        
        await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error in gm_leaderboard: {str(e)}")
        await update.message.reply_text("Sorry, there was an error getting the leaderboard. Please try again later!")
    finally:
        conn.close()

async def ping(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Sorry, I'm awake! Good morning! ☀️")

async def about(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("🌞 Good Morning Bot run by @lun4rsea! ☕✨")

async def handle_gm(update: Update, context: CallbackContext) -> None:
    """Handle good morning messages and store data uniquely per group."""
    if not check_gm(update.message.text):
        return
        
    user = update.message.from_user
    chat_id = update.message.chat_id
    
    if chat_id == user.id:
        await update.message.reply_text("Sorry, you need to say this in a group!")
        return
    
    try:
        table_name = ensure_group_table(chat_id)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Ensure the table exists before any operations
        cursor.execute(f"SELECT last_gm, streak, longest_streak FROM {table_name} WHERE user_id = ?", (user.id,))
        result = cursor.fetchone()
        today = datetime.now().date()
        
        if result:
            last_gm, streak, longest_streak = result
            last_gm = datetime.strptime(last_gm, "%Y-%m-%d").date() if last_gm else None
            
            if last_gm == today:
                conn.close()
                return
            
            new_streak = streak + 1 if last_gm == today - timedelta(days=1) else 1
            new_longest_streak = max(longest_streak, new_streak)
            
            cursor.execute(f"""
                UPDATE {table_name}
                SET last_gm = ?, total_gm = total_gm + 1, streak = ?, longest_streak = ?
                WHERE user_id = ?
            """, (today, new_streak, new_longest_streak, user.id))
        else:
            new_streak = 1
            cursor.execute(f"""
                INSERT INTO {table_name} (user_id, username, last_gm, total_gm, streak, longest_streak)
                VALUES (?, ?, ?, 1, 1, 1)
            """, (user.id, user.username, today))
        
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Good morning, {user.first_name}! ☀️ Your streak is now {new_streak}.")
    except Exception as e:
        logger.error(f"Error in handle_gm: {str(e)}")
        await update.message.reply_text("Sorry, there was an error processing your good morning. Please try again later!")

def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gm))
    app.add_handler(CommandHandler("GMLB", gm_leaderboard))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("about", about))
    app.run_polling()

if __name__ == "__main__":
    main()

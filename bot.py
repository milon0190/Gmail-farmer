import logging
import sqlite3
import datetime
import re
import secrets
import string
import os
from typing import Dict, List, Optional, Tuple, Any
from dotenv import load_dotenv

# --- IMPORTS FIXED FOR v20+ ---
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    KeyboardButton, ReplyKeyboardMarkup
)
# ParseMode moved to constants in v20
from telegram.constants import ParseMode 
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# --- 1. ENVIRONMENT CONFIGURATION SYSTEM ---
load_dotenv()

class Config:
    """Centralized Configuration Management using Environment Variables."""
    
    # Bot Credentials
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    # Admin Settings (Parse comma-separated IDs)
    ADMIN_IDS = []
    if os.getenv("ADMIN_IDS"):
        try:
            ADMIN_IDS = [int(uid.strip()) for uid in os.getenv("ADMIN_IDS").split(",") if uid.strip().isdigit()]
        except ValueError:
            logging.warning("Invalid ADMIN_IDS format in .env file")

    # Database Settings
    DB_NAME = os.getenv("DB_NAME", "gmail_bot.db")
    
    # System Settings
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

    @classmethod
    def validate(cls):
        """Validates critical configuration."""
        if not cls.BOT_TOKEN:
            raise ValueError("❌ CRITICAL: BOT_TOKEN is missing in .env file!")
        return True

# Initialize Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=Config.LOG_LEVEL
)
logger = logging.getLogger(__name__)

# Conversation States
(
    ENTER_GMAIL, ENTER_PASSWORD, ENTER_WITHDRAW_AMOUNT, ENTER_WITHDRAW_NUMBER,
    ENTER_PAYMENT_METHOD_NAME, ENTER_USER_ID, ENTER_BALANCE_AMOUNT, 
    ENTER_MIN_WITHDRAW_AMOUNT, ENTER_GMAIL_ID, SELECT_GMAIL_ACTION,
    ENTER_GMAIL_PRICE, ENTER_WITHDRAW_ID, SELECT_WITHDRAW_ACTION,
    ENTER_BROADCAST_MESSAGE, ADMIN_ADD_BALANCE_UID, ADMIN_ADD_BALANCE_AMT,
    ENTER_REJECT_REASON, ENTER_SUPPORT_MSG, ADMIN_REPLY_SUPPORT, ADMIN_BAN_UID,
    # V4/V5 States
    ADMIN_SEARCH_USER, ADMIN_USER_ACTION_SELECT, 
    ADMIN_EDIT_SETTING_KEY, ADMIN_EDIT_SETTING_VAL,
    ADMIN_CREATE_PROMO_CODE, ADMIN_PROMO_AMOUNT, ADMIN_PROMO_LIMIT,
    ENTER_PROMO_REDEEM
) = range(28)

# --- Helper Utilities ---

def escape_html(text: str) -> str:
    if not text: return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

class TextManager:
    @staticmethod
    def welcome():
        return (
            "💎 <b>Welcome to Gmail Buy Bot ULTIMATE V5 (Env)!</b> 💎\n\n"
            "✨ <i>The #1 Premium Platform with Secure Config.</i>\n\n"
            "🚀 <b>Start Earning Today!</b>"
        )

    @staticmethod
    def profile(user_data: dict, ref_stats: dict):
        return (
            f"┌───────────────────────┐\n"
            f"│    <b>USER PROFILE</b>    │\n"
            f"└───────────────────────┘\n\n"
            f"🆔 <b>User ID:</b> <code>{user_data['user_id']}</code>\n"
            f"👤 <b>Name:</b> {escape_html(user_data['first_name'])}\n"
            f"───────────────────────\n"
            f"💰 <b>Wallet Balance</b>\n"
            f"<code>৳ {user_data['balance']:.2f} BDT</code>\n"
            f"───────────────────────\n\n"
            f"📧 <b>Gmail Sold:</b> {user_data['gmail_sell_count']}\n"
            f"💳 <b>Total Withdrawn:</b> <code>৳{user_data['total_withdraw']:.2f}</code>\n"
            f"🤝 <b>Referrals:</b> {ref_stats['count']} Users\n"
            f"💎 <b>Ref. Earnings:</b> <code>৳{ref_stats['earnings']:.2f}</code>"
        )

class KeyboardManager:
    @staticmethod
    def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
        buttons = [
            [KeyboardButton("💎 My Account"), KeyboardButton("📧 Sell Gmail")],
            [KeyboardButton("💸 Withdraw Money"), KeyboardButton("🎁 Daily Bonus")],
            [KeyboardButton("👥 Refer & Earn"), KeyboardButton("🎟️ Support")],
            [KeyboardButton("📜 History"), KeyboardButton("🏷️ Redeem Code")]
        ]
        if is_admin:
            buttons.append([KeyboardButton("🛡️ Admin Panel")])
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    @staticmethod
    def back_main_inline():
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]])

    @staticmethod
    def cancel_inline():
        return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]])

# --- Database Manager V5 ---
class Database:
    def __init__(self, db_name: str = None):
        # Use Config DB name or default
        self.db_path = db_name or Config.DB_NAME
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row 
        self.create_tables()
        self.upgrade_database()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0,
                gmail_sell_count INTEGER DEFAULT 0,
                total_withdraw REAL DEFAULT 0,
                is_admin BOOLEAN DEFAULT FALSE,
                is_banned BOOLEAN DEFAULT FALSE,
                last_daily_claim TIMESTAMP DEFAULT NULL,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                referral_earnings REAL DEFAULT 0
            )
        ''')
        
        # Gmails
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gmail_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gmail TEXT UNIQUE,
                password TEXT,
                amount REAL DEFAULT 5.0,
                status TEXT DEFAULT 'pending',
                submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reject_reason TEXT
            )
        ''')
        
        # Withdrawals
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                method TEXT,
                number TEXT,
                status TEXT DEFAULT 'pending',
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Support
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                reply TEXT DEFAULT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Promo Codes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                amount REAL,
                uses_left INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')

        # Payment Methods
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Settings
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # Defaults
        cursor.execute('''
            INSERT OR IGNORE INTO settings (key, value) 
            VALUES ('min_withdraw', '100.0'), ('gmail_price', '5.0'), ('referral_commission', '5.0'), ('daily_bonus_amount', '2.0')
        ''')

        self.add_payment_method("bKash")
        self.add_payment_method("Nagad")
        self.add_payment_method("Rocket")
        self.add_payment_method("Recharge/Skrill")

        self.conn.commit()

    def upgrade_database(self):
        cursor = self.conn.cursor()
        try: cursor.execute("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE")
        except: pass
        try: cursor.execute("ALTER TABLE users ADD COLUMN last_daily_claim TIMESTAMP DEFAULT NULL")
        except: pass
        self.conn.commit()
    
    def generate_referral_code(self):
        return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))

    # --- Promo Logic ---
    def create_promo_code(self, code: str, amount: float, limit: int):
        cursor = self.conn.cursor()
        try:
            cursor.execute('INSERT INTO promo_codes (code, amount, uses_left) VALUES (?, ?, ?)', (code, amount, limit))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError: return False

    def use_promo_code(self, code: str, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM promo_codes WHERE code = ? AND is_active = TRUE', (code,))
        promo = cursor.fetchone()
        
        if not promo: return False, "Invalid Code"
        if promo['uses_left'] <= 0: return False, "Code Expired"
        
        cursor.execute('UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?', (code,))
        self.update_balance(user_id, promo['amount'])
        self.conn.commit()
        return True, f"Success! +৳{promo['amount']} added."

    # --- User & Balance ---
    def get_user(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    def create_user(self, user_id: int, username: str, first_name: str, referrer_id: int = None):
        cursor = self.conn.cursor()
        try:
            ref_code = self.generate_referral_code()
            # Check if user is in ENV Admin list
            is_admin = user_id in Config.ADMIN_IDS
            
            cursor.execute('INSERT INTO users (user_id, username, first_name, referral_code, referred_by, is_admin) VALUES (?, ?, ?, ?, ?, ?)', 
                           (user_id, username, first_name, ref_code, referrer_id, is_admin))
            self.conn.commit()
        except: pass
    
    def ban_user(self, user_id: int):
        self.conn.execute('UPDATE users SET is_banned = TRUE WHERE user_id = ?', (user_id,))
        self.conn.commit()

    def unban_user(self, user_id: int):
        self.conn.execute('UPDATE users SET is_banned = FALSE WHERE user_id = ?', (user_id,))
        self.conn.commit()
        
    def update_balance(self, user_id: int, amount: float):
        self.conn.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
        self.conn.commit()

    def search_user(self, query: str):
        cursor = self.conn.cursor()
        try:
            uid = int(query)
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (uid,))
            return cursor.fetchall()
        except ValueError:
            cursor.execute('SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ? LIMIT 5', (f'%{query}%', f'%{query}%'))
            return cursor.fetchall()

    # --- Settings ---
    def update_setting(self, key: str, value: str):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
        self.conn.commit()
        
    def get_setting(self, key: str):
        cursor = self.conn.cursor()
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        return float(result[0]) if result else None

    # --- Gmail Logic ---
    def add_gmail_submission(self, user_id: int, gmail: str, password: str, amount: float = 5.0):
        cursor = self.conn.cursor()
        try:
            cursor.execute('INSERT INTO gmail_submissions (user_id, gmail, password, amount) VALUES (?, ?, ?, ?)', (user_id, gmail, password, amount))
            self.conn.commit()
            return True
        except: return False

    def get_gmails_by_status_paginated(self, status: str, offset=0, limit=10):
        cursor = self.conn.cursor()
        cursor.execute('SELECT gs.*, u.first_name FROM gmail_submissions gs JOIN users u ON gs.user_id = u.user_id WHERE gs.status = ? ORDER BY gs.submission_date DESC LIMIT ? OFFSET ?', (status, limit, offset))
        return cursor.fetchall()

    def get_gmail_by_id(self, gid): 
        c=self.conn.cursor(); c.execute('SELECT * FROM gmail_submissions WHERE id=?',(gid,)); return c.fetchone()

    def update_gmail_status(self, gid, status, reason=None):
        c=self.conn.cursor()
        g = self.get_gmail_by_id(gid)
        if not g: return False
        
        c.execute('UPDATE gmail_submissions SET status=?, reject_reason=? WHERE id=?', (status, reason, gid))
        
        if status == 'success':
            self.update_balance(g['user_id'], g['amount'])
            c.execute('UPDATE users SET gmail_sell_count = gmail_sell_count + 1 WHERE user_id = ?', (g['user_id'],))
        elif status == 'rejected' and g['status'] == 'success':
             self.update_balance(g['user_id'], -g['amount'])
             c.execute('UPDATE users SET gmail_sell_count = gmail_sell_count - 1 WHERE user_id = ?', (g['user_id'],))
        
        self.conn.commit()
        return True

    # --- Withdraw Logic ---
    def add_withdrawal(self, uid, amt, method, num):
        bal = self.get_user_balance(uid)
        if bal < amt: return None
        self.conn.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amt, uid))
        self.conn.execute('INSERT INTO withdrawals (user_id, amount, method, number) VALUES (?,?,?,?)', (uid, amt, method, num))
        self.conn.commit()
        return self.conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    def get_withdrawals_by_status_paginated(self, status, offset=0, limit=10):
        c=self.conn.cursor()
        c.execute('SELECT w.*, u.first_name FROM withdrawals w JOIN users u ON w.user_id = u.user_id WHERE w.status = ? ORDER BY w.request_date DESC LIMIT ? OFFSET ?', (status, limit, offset))
        return c.fetchall()

    def get_withdrawal_by_id(self, wid):
        c=self.conn.cursor(); c.execute('SELECT * FROM withdrawals WHERE id=?',(wid,)); return c.fetchone()

    def update_withdrawal_status(self, wid, status):
        w = self.get_withdrawal_by_id(wid)
        if not w: return False
        
        if status == 'rejected':
            self.conn.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (w['amount'], w['user_id']))
        elif status == 'success':
            self.conn.execute('UPDATE users SET total_withdraw = total_withdraw + ? WHERE user_id = ?', (w['amount'], w['user_id']))
            
        self.conn.execute('UPDATE withdrawals SET status=? WHERE id=?', (status, wid))
        self.conn.commit()
        return True

    # --- Helpers ---
    def get_user_balance(self, uid):
        r=self.conn.execute('SELECT balance FROM users WHERE user_id=?', (uid,)).fetchone()
        return r[0] if r else 0
    
    def get_referral_stats(self, uid):
        c=self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM users WHERE referred_by=?', (uid,))
        count=c.fetchone()[0]
        c.execute('SELECT referral_earnings, referral_code FROM users WHERE user_id=?', (uid,))
        d=c.fetchone()
        return {"count": count, "earnings": d[0] if d and d[0] else 0.0, "code": d[1]}

    def get_stats(self):
        c=self.conn.cursor()
        c.execute('SELECT COUNT(*), SUM(balance), SUM(gmail_sell_count) FROM users')
        u=c.fetchone()
        c.execute('SELECT COUNT(*) FROM gmail_submissions WHERE status="pending"')
        pg=c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM withdrawals WHERE status="pending"')
        pw=c.fetchone()[0]
        return {"total_users": u[0], "total_balance": u[1] or 0, "total_sold": u[2] or 0, "pending_gmails": pg, "pending_withdrawals": pw}
    
    def get_payment_methods(self):
        return self.conn.execute('SELECT * FROM payment_methods WHERE is_active=TRUE').fetchall()

    def get_all_user_ids(self):
        return [r[0] for r in self.conn.execute('SELECT user_id FROM users').fetchall()]

    def get_user_gmails(self, uid):
        return self.conn.execute('SELECT * FROM gmail_submissions WHERE user_id=? ORDER BY submission_date DESC', (uid,)).fetchall()
    def get_user_withdrawals(self, uid):
        return self.conn.execute('SELECT * FROM withdrawals WHERE user_id=? ORDER BY request_date DESC', (uid,)).fetchall()
    def get_user_tickets(self, uid):
        return self.conn.execute('SELECT * FROM support_tickets WHERE user_id=? ORDER BY created_at DESC', (uid,)).fetchall()
    def get_pending_tickets(self):
        return self.conn.execute('SELECT st.*, u.first_name FROM support_tickets st JOIN users u ON st.user_id = u.user_id WHERE st.status="pending"').fetchall()
    def create_ticket(self, uid, msg):
        self.conn.execute('INSERT INTO support_tickets (user_id, message) VALUES (?, ?)', (uid, msg))
        self.conn.commit()
    def reply_ticket(self, tid, reply):
        c=self.conn.cursor()
        c.execute('UPDATE support_tickets SET reply=?, status="closed" WHERE id=?', (reply, tid))
        c.execute('SELECT user_id FROM support_tickets WHERE id=?', (tid,))
        self.conn.commit()
        return c.fetchone()['user_id']

# Initialize Database with Config
try:
    db = Database(Config.DB_NAME)
    logger.info(f"Database connected: {Config.DB_NAME}")
except Exception as e:
    logger.error(f"Database connection failed: {e}")
    exit(1)

# --- Bot Logic V5 ---

class GmailBuyBot:
    def __init__(self):
        try:
            self.application = Application.builder().token(Config.BOT_TOKEN).build()
        except ValueError as e:
            logger.critical(f"Configuration Error: {e}")
            exit(1)
        self.setup_handlers()
    
    async def send_typing_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query: await update.callback_query.answer()
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start))
        
        # User Conversations
        conv_handler_gmail = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_gmail_sell, pattern='^gmail_sell$')],
            states={
                ENTER_GMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_gmail)],
                ENTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_password)],
            },
            fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern='^cancel$')]
        )
        
        conv_handler_withdraw = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.withdraw_method_select, pattern='^withdraw$')],
            states={
                ENTER_WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_withdraw_amount)],
                ENTER_WITHDRAW_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_withdraw_number)],
            },
            fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern='^cancel$')]
        )
        
        conv_handler_redeem = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.user_redeem_start, pattern='^user_redeem$')],
            states={ENTER_PROMO_REDEEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.user_enter_redeem_code)]},
            fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern='^cancel$')]
        )

        # Admin Master Conversation
        conv_handler_admin = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.admin_panel_menu, pattern='^admin_panel$'),
                CallbackQueryHandler(self.admin_user_search_start, pattern='^admin_user_search$'),
                CallbackQueryHandler(self.admin_edit_settings_start, pattern='^admin_edit_settings$'),
                CallbackQueryHandler(self.admin_create_promo_start, pattern='^admin_create_promo$'),
                CallbackQueryHandler(self.admin_review_gmail, pattern='^review_gmail_by_id$'),
                CallbackQueryHandler(self.admin_review_withdraw_id, pattern='^review_withdraw_by_id$'),
                CallbackQueryHandler(self.admin_reply_support_start, pattern='^admin_reply_support$'),
                CallbackQueryHandler(self.admin_user_action_select, pattern='^adm_user_act_'),
                CallbackQueryHandler(self.admin_handle_setting_action, pattern='^set_(gmail_price|min_withdraw|daily_bonus)$')
            ],
            states={
                ADMIN_SEARCH_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_perform_search)],
                ADMIN_USER_ACTION_SELECT: [CallbackQueryHandler(self.admin_perform_user_action, pattern='^adm_do_')],
                ADMIN_EDIT_SETTING_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_edit_setting_key)],
                ADMIN_EDIT_SETTING_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_edit_setting_val)],
                ADMIN_CREATE_PROMO_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_enter_promo_code)],
                ADMIN_PROMO_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_enter_promo_amount)],
                ADMIN_PROMO_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_enter_promo_limit)],
                ENTER_GMAIL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_enter_gmail_id)],
                ENTER_WITHDRAW_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_enter_withdraw_id)],
                ADMIN_REPLY_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_enter_support_reply)],
                SELECT_GMAIL_ACTION: [CallbackQueryHandler(self.admin_handle_gmail_action, pattern='^(approve_gmail|pending_gmail)$')],
                SELECT_WITHDRAW_ACTION: [CallbackQueryHandler(self.admin_handle_withdraw_action, pattern='^(approve_withdraw|reject_withdraw)$')],
            },
            fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern='^cancel$')]
        )
        
        conv_handler_support = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.user_start_support, pattern='^user_support$')],
            states={ENTER_SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.user_enter_support_msg)]},
            fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern='^cancel$')]
        )

        self.application.add_handler(conv_handler_gmail)
        self.application.add_handler(conv_handler_withdraw)
        self.application.add_handler(conv_handler_admin)
        self.application.add_handler(conv_handler_support)
        self.application.add_handler(conv_handler_redeem)
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    # --- Core ---
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user.id: db.create_user(user.id, user.username, user.first_name)
        await self.show_main_menu(update, context)

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = None):
        if text is None: text = TextManager.welcome()
        user = db.get_user(update.effective_user.id)
        markup = KeyboardManager.main_menu(user['is_admin'] if user else False)
        if update.message:
            await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        else:
            try: await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            except: pass

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        handlers = {
            "💎 My Account": self.show_account, "📧 Sell Gmail": self.show_gmail_sell_info,
            "💸 Withdraw Money": self.show_withdraw_info, "👥 Refer & Earn": self.show_referral_system,
            "📜 History": self.show_history, "🛡️ Admin Panel": self.show_admin_landing,
            "🔙 Back": self.show_main_menu, "🎁 Daily Bonus": self.show_daily_bonus,
            "🎟️ Support": self.show_support_menu, "🏷️ Redeem Code": self.user_redeem_landing
        }
        if text in handlers: await handlers[text](update, context)
        else: await self.show_main_menu(update, context, "⚠️ Use buttons.")

    # --- User Features ---
    async def show_account(self, u, c):
        await self.send_typing_action(u, c)
        d = db.get_user(u.effective_user.id)
        s = db.get_referral_stats(u.effective_user.id)
        await u.message.reply_text(TextManager.profile(d, s), parse_mode=ParseMode.HTML)

    async def show_daily_bonus(self, u, c):
        user = db.get_user(u.effective_user.id)
        now = datetime.datetime.now()
        if not user['last_daily_claim']:
            amt = db.get_setting('daily_bonus_amount')
            db.update_balance(u.effective_user.id, amt)
            db.conn.execute('UPDATE users SET last_daily_claim=? WHERE user_id=?', (now, u.effective_user.id))
            db.conn.commit()
            await u.message.reply_text(f"🎁 Bonus Claimed! +৳{amt}", parse_mode=ParseMode.HTML)
        else:
            last = datetime.datetime.strptime(user['last_daily_claim'], '%Y-%m-%d %H:%M:%S')
            if (now - last).days >= 1:
                amt = db.get_setting('daily_bonus_amount')
                db.update_balance(u.effective_user.id, amt)
                db.conn.execute('UPDATE users SET last_daily_claim=? WHERE user_id=?', (now, u.effective_user.id))
                db.conn.commit()
                await u.message.reply_text(f"🎁 Bonus Claimed! +৳{amt}", parse_mode=ParseMode.HTML)
            else:
                await u.message.reply_text("⏳ Already claimed today.", parse_mode=ParseMode.HTML)

    async def user_redeem_landing(self, u, c):
        await u.message.reply_text("🏷️ <b>Enter Promo Code:</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)

    async def user_redeem_start(self, u, c):
        await c.answer()
        await u.callback_query.edit_message_text("🏷️ <b>Enter Code:</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
        return ENTER_PROMO_REDEEM

    async def user_enter_redeem_code(self, u, c):
        code = u.message.text.strip().upper()
        success, msg = db.use_promo_code(code, u.effective_user.id)
        await u.message.reply_text(msg, reply_markup=KeyboardManager.main_menu(False), parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    # --- Admin V5 System ---
    async def show_admin_landing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not db.get_user(update.effective_user.id)['is_admin']:
            return await update.message.reply_text("🚫 Access Denied")
        keyboard = [[InlineKeyboardButton("🛡️ Enter Admin Panel", callback_data="admin_panel")]]
        await update.message.reply_text("🔐 <b>Admin Verification Required</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    async def admin_panel_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = db.get_stats()
        text = (
            "🛡️ <b>ADMIN CONTROL CENTER V5</b>\n\n"
            f"👥 Users: <code>{stats['total_users']}</code>\n"
            f"💰 Total Balance: <code>৳{stats['total_balance']:.2f}</code>\n"
            f"⚠️ Pending: 📧 {stats['pending_gmails']} | 💸 {stats['pending_withdrawals']}"
        )
        keyboard = [
            [InlineKeyboardButton("📊 Dashboard", callback_data="admin_panel")],
            [InlineKeyboardButton("👥 Manage Users", callback_data="admin_user_search")],
            [InlineKeyboardButton("📧 Review Gmails", callback_data="admin_gmails_pending_0")],
            [InlineKeyboardButton("💸 Review Withdrawals", callback_data="admin_withdrawals_pending_0")],
            [InlineKeyboardButton("⚙️ System Settings", callback_data="admin_edit_settings")],
            [InlineKeyboardButton("🎟️ Create Promo", callback_data="admin_create_promo")],
            [InlineKeyboardButton("🔙 Back to Bot", callback_data="back_main")]
        ]
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    # 1. Advanced User Management
    async def admin_user_search_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text("🔍 <b>Search User (ID or Name):</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
        return ADMIN_SEARCH_USER

    async def admin_perform_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.message.text.strip()
        results = db.search_user(query)
        if not results:
            return await update.message.reply_text("❌ No user found.", reply_markup=KeyboardManager.cancel_inline())
        
        text = "👥 <b>Search Results:</b>\n\n"
        keyboard = []
        for u in results:
            text += f"🆔 {u['user_id']} | {escape_html(u['first_name'])}\n💰 ৳{u['balance']:.2f}\n"
            keyboard.append([InlineKeyboardButton(f"Manage {u['first_name']}", callback_data=f"adm_user_act_{u['user_id']}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel")])
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    async def admin_user_action_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target_id = int(update.callback_query.data.split('_')[-1])
        context.user_data['admin_target_uid'] = target_id
        u = db.get_user(target_id)
        
        text = (
            f"👤 <b>User Profile</b>\n\n"
            f"🆔 ID: <code>{u['user_id']}</code>\n"
            f"👤 Name: {escape_html(u['first_name'])}\n"
            f"🔗 Username: @{u['username'] or 'N/A'}\n"
            f"💰 Balance: <code>৳{u['balance']:.2f}</code>\n"
            f"📧 Sold: {u['gmail_sell_count']}\n"
            f"🚫 Banned: {'Yes' if u['is_banned'] else 'No'}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("💰 Add Balance", callback_data="adm_do_addbal")],
            [InlineKeyboardButton("⛔ Ban User" if not u['is_banned'] else "✅ Unban User", callback_data="adm_do_ban")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_user_search")]
        ]
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return ADMIN_USER_ACTION_SELECT

    async def admin_perform_user_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        action = update.callback_query.data.split('_')[-1]
        uid = context.user_data['admin_target_uid']
        
        if action == "addbal":
            await update.callback_query.edit_message_text("💰 <b>Enter Amount to Add:</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
            await update.callback_query.message.reply_text("⚠️ Use Admin Add Balance tool in full version.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="adm_user_act_{}".format(uid))]]))
            return ADMIN_USER_ACTION_SELECT
        elif action == "ban":
            u = db.get_user(uid)
            if u['is_banned']: db.unban_user(uid)
            else: db.ban_user(uid)
            await update.callback_query.answer("✅ Status Updated")
            return await self.admin_user_action_select(update, context)
            
    # 2. Live Settings
    async def admin_edit_settings_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = "⚙️ <b>Edit System Settings</b>\n\nCurrent Rates:\n"
        text += f"📧 Gmail Price: ৳{db.get_setting('gmail_price')}\n"
        text += f"📉 Min Withdraw: ৳{db.get_setting('min_withdraw')}\n"
        text += f"🎁 Daily Bonus: ৳{db.get_setting('daily_bonus_amount')}\n"
        
        keyboard = [
            [InlineKeyboardButton("Set Gmail Price", callback_data="set_gmail_price")],
            [InlineKeyboardButton("Set Min Withdraw", callback_data="set_min_withdraw")],
            [InlineKeyboardButton("Set Daily Bonus", callback_data="set_daily_bonus")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
        ]
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    async def admin_handle_setting_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        key = update.callback_query.data.split('_')[-1]
        context.user_data['setting_key'] = key
        labels = {
            'gmail_price': 'New Gmail Price',
            'min_withdraw': 'New Min Withdraw',
            'daily_bonus': 'New Daily Bonus'
        }
        await update.callback_query.edit_message_text(f"✏️ <b>{labels[key]}:</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
        return ADMIN_EDIT_SETTING_VAL

    async def admin_edit_setting_val(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            key = context.user_data['setting_key']
            db.update_setting(key, val)
            await update.message.reply_text(f"✅ {key} updated to {val}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_edit_settings")]]), parse_mode=ParseMode.HTML)
            return ConversationHandler.END
        except:
            return await update.message.reply_text("❌ Invalid Number")

    # 3. Promo Code System
    async def admin_create_promo_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text("🎟️ <b>Create New Promo Code</b>\n\nEnter Code Name (e.g. DIWALI50):", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
        return ADMIN_CREATE_PROMO_CODE

    async def admin_enter_promo_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        code = update.message.text.strip().upper()
        context.user_data['promo_code'] = code
        await update.message.reply_text(f"💰 <b>Enter Bonus Amount for {code}:</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
        return ADMIN_PROMO_AMOUNT

    async def admin_enter_promo_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            amt = float(update.message.text)
            context.user_data['promo_amt'] = amt
            await update.message.reply_text("🔢 <b>Enter Usage Limit (e.g. 100):</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
            return ADMIN_PROMO_LIMIT
        except: return await update.message.reply_text("❌ Invalid Number")

    async def admin_enter_promo_limit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            limit = int(update.message.text)
            code = context.user_data['promo_code']
            amt = context.user_data['promo_amt']
            
            if db.create_promo_code(code, amt, limit):
                await update.message.reply_text(f"✅ <b>Promo Created!</b>\nCode: {code}\nAmount: ৳{amt}\nLimit: {limit}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]), parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text("❌ Code already exists.")
            return ConversationHandler.END
        except: return await update.message.reply_text("❌ Invalid Number")

    # --- Review Systems ---
    async def admin_review_gmail(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text("🔍 <b>Enter Gmail ID to Review:</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
        return ENTER_GMAIL_ID

    async def admin_enter_gmail_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            gid = int(update.message.text)
            g = db.get_gmail_by_id(gid)
            if not g: return await update.message.reply_text("❌ Not Found")
            
            context.user_data['review_gid'] = gid
            txt = f"📧 <b>Review #{g['id']}</b>\nUser: {g['first_name']}\nGmail: {g['gmail']}\nPass: {g['password']}\nStatus: {g['status']}"
            k = [
                [InlineKeyboardButton("✅ Approve", callback_data="approve_gmail")],
                [InlineKeyboardButton("❌ Reject", callback_data="reject_gmail_direct")]
            ]
            if g['status'] != 'pending': k.append([InlineKeyboardButton("⏳ Set Pending", callback_data="pending_gmail")])
            k.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel")])
            await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(k), parse_mode=ParseMode.HTML)
            return SELECT_GMAIL_ACTION
        except: return await update.message.reply_text("❌ Invalid ID")

    async def admin_handle_gmail_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        act = update.callback_query.data
        gid = context.user_data['review_gid']
        status = 'success' if act == 'approve_gmail' else 'pending' if act == 'pending_gmail' else 'rejected'
        
        db.update_gmail_status(gid, status)
        await update.callback_query.answer(f"✅ Marked {status}")
        if status == 'success':
            g = db.get_gmail_by_id(gid)
            try: await context.bot.send_message(g['user_id'], f"✅ Your Gmail was approved! +৳{g['amount']}", parse_mode=ParseMode.HTML)
            except: pass
        return ConversationHandler.END

    async def admin_review_withdraw_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text("🔍 <b>Enter Withdrawal ID:</b>", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML)
        return ENTER_WITHDRAW_ID

    async def admin_enter_withdraw_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            wid = int(update.message.text)
            w = db.get_withdrawal_by_id(wid)
            if not w: return await update.message.reply_text("❌ Not Found")
            
            context.user_data['review_wid'] = wid
            txt = f"💸 <b>Withdrawal #{w['id']}</b>\nUser: {w['first_name']}\nAmt: ৳{w['amount']}\nMethod: {w['method']}\nNum: {w['number']}"
            k = [[InlineKeyboardButton("✅ Pay", callback_data="approve_withdraw")], [InlineKeyboardButton("❌ Reject", callback_data="reject_withdraw")], [InlineKeyboardButton("🔙", callback_data="admin_panel")]]
            await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(k), parse_mode=ParseMode.HTML)
            return SELECT_WITHDRAW_ACTION
        except: return await update.message.reply_text("❌ Invalid ID")

    async def admin_handle_withdraw_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        act = update.callback_query.data
        wid = context.user_data['review_wid']
        status = 'success' if act == 'approve_withdraw' else 'rejected'
        db.update_withdrawal_status(wid, status)
        await update.callback_query.answer(f"✅ {status}")
        return ConversationHandler.END

    # --- Standard Handlers ---
    async def show_gmail_sell_info(self, u, c):
        p = db.get_setting('gmail_price')
        k = [[InlineKeyboardButton("🚀 Start Selling", callback_data="gmail_sell")], [InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
        await u.message.reply_text(f"📧 <b>Sell Gmail</b>\nRate: ৳{p}", reply_markup=InlineKeyboardMarkup(k), parse_mode=ParseMode.HTML)

    async def start_gmail_sell(self, u, c): await u.callback_query.edit_message_text("Send Gmail:", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML); return ENTER_GMAIL
    async def enter_gmail(self, u, c): c.user_data['temp_gmail']=u.message.text; await u.message.reply_text("Send Password:", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML); return ENTER_PASSWORD
    async def enter_password(self, u, c): 
        db.add_gmail_submission(u.effective_user.id, c.user_data['temp_gmail'], u.message.text, db.get_setting('gmail_price'))
        await u.message.reply_text("✅ Submitted!", reply_markup=KeyboardManager.main_menu(False), parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    async def show_withdraw_info(self, u, c):
        bal = db.get_user_balance(u.effective_user.id)
        k = [[InlineKeyboardButton("💸 Request", callback_data="withdraw")], [InlineKeyboardButton("🔙 Back", callback_data="back_main")]] if bal >= 100 else [[InlineKeyboardButton("❌ Low Bal", callback_data="ignore")]]
        await u.message.reply_text(f"💸 Withdraw\nBal: ৳{bal}", reply_markup=InlineKeyboardMarkup(k), parse_mode=ParseMode.HTML)
    
    async def withdraw_method_select(self, u, c): 
        ms = db.get_payment_methods()
        k = [[InlineKeyboardButton(m['name'], callback_data=f"wmethod_{m['id']}")] for m in ms]
        k.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        await u.callback_query.edit_message_text("Select Method:", reply_markup=InlineKeyboardMarkup(k), parse_mode=ParseMode.HTML)
        return ENTER_WITHDRAW_AMOUNT

    async def enter_withdraw_amount(self, u, c):
        amt = float(u.message.text)
        if amt < 100 or amt > db.get_user_balance(u.effective_user.id): return await u.message.reply_text("❌ Invalid Amount", reply_markup=KeyboardManager.cancel_inline())
        c.user_data['w_amt']=amt; await u.message.reply_text("Enter Number:", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML); return ENTER_WITHDRAW_NUMBER

    async def enter_withdraw_number(self, u, c):
        db.add_withdrawal(u.effective_user.id, c.user_data['w_amt'], "bKash", u.message.text)
        await u.message.reply_text("✅ Request Sent!", reply_markup=KeyboardManager.main_menu(False), parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    async def show_history(self, u, c):
        k = [[InlineKeyboardButton("📧 Gmail", callback_data="hist_gmail")], [InlineKeyboardButton("💸 Withdraw", callback_data="hist_withdraw")], [InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
        await u.message.reply_text("Select History", reply_markup=InlineKeyboardMarkup(k), parse_mode=ParseMode.HTML)

    async def show_referral_system(self, u, c): await u.message.reply_text("🔗 Referral Link Feature", reply_markup=KeyboardManager.back_main_inline(), parse_mode=ParseMode.HTML)
    async def show_support_menu(self, u, c): await u.message.reply_text("🎟️ Support Feature", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("New Ticket", callback_data="user_support")], [InlineKeyboardButton("🔙", callback_data="back_main")]]), parse_mode=ParseMode.HTML)
    async def user_start_support(self, u, c): await u.callback_query.edit_message_text("Send msg:", reply_markup=KeyboardManager.cancel_inline(), parse_mode=ParseMode.HTML); return ENTER_SUPPORT_MSG
    async def user_enter_support_msg(self, u, c): await u.message.reply_text("✅ Sent", reply_markup=KeyboardManager.main_menu(False), parse_mode=ParseMode.HTML); return ConversationHandler.END
    async def admin_reply_support_start(self, u, c): pass
    async def admin_enter_support_reply(self, u, c): pass

    async def button_handler(self, u, c):
        q=u.callback_query; data=q.data; await q.answer()
        if data=="back_main": await self.show_main_menu(u,c)
        elif data.startswith("admin_gmails_"): await q.edit_message_text("Gmail List View", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_panel")]]))
        elif data.startswith("admin_withdrawals_"): await q.edit_message_text("Withdraw List View", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="admin_panel")]]))
    
    async def cancel_operation(self, u, c): await self.show_main_menu(u,c); return ConversationHandler.END
    async def admin_edit_setting_key(self, u, c): pass 

if __name__ == '__main__':
    # Validate Config before starting
    if Config.validate():
        bot = GmailBuyBot()
        logger.info("Bot started successfully with Env Configuration.")
        bot.application.run_polling()

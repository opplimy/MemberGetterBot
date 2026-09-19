import os
import html
from datetime import datetime, timezone

from dotenv import load_dotenv

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from database import init_db, connect, get_setting, set_setting, add_diamonds


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8394607974"))
MISSION_CHANNEL = "@membersbyte"
RETENTION_SECONDS = 4 * 24 * 60 * 60
MISSION_PENALTY = 3

REQUIRED_CHANNELS = [
    "@ByteTunnel",
    "@membersbyte",
]

PRICE_KEYS = {
    "5": "price_5",
    "10": "price_10",
    "15": "price_15",
    "20": "price_20",
    "60": "price_60",
    "100": "price_100",
}

PRICE_DEFAULTS = {
    "price_5": 10,
    "price_10": 20,
    "price_15": 30,
    "price_20": 35,
    "price_60": 80,
    "price_100": 120,
}


# =========================================================
# GENERAL KEYBOARDS
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["💎 دریافت الماس رایگان 💎"],
            ["🚀 سفارش ممبر 🚀"],
            ["🔐 حساب کاربری 🔐", "👥 زیر مجموعه گیری 👥"],
            ["📚 راهنما ⁉️"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📊 آمار", "👥 مدیریت کاربران"],
            ["💎 مدیریت الماس", "🚫 بن / آنبن"],
            ["📢 مدیریت کانال‌ها", "➕ افزودن کانال"],
            ["💰 مدیریت پاداش‌ها", "💵 مدیریت قیمت‌ها"],
            ["🔎 جستجوی کاربر", "📋 لیست کانال‌ها"],
            ["📦 سفارشات", "🏠 منوی اصلی"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["❌ لغو"],
            ["🏠 منوی ادمین"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def back_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🔙 بازگشت"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def required_channels_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 عضویت در @ByteTunnel",
                url="https://t.me/ByteTunnel",
            )
        ],
        [
            InlineKeyboardButton(
                "📢 عضویت در @membersbyte",
                url="https://t.me/membersbyte",
            )
        ],
        [
            InlineKeyboardButton(
                "✅ بررسی عضویت",
                callback_data="check_required",
            )
        ],
    ])


# =========================================================
# DATABASE HELPERS
# =========================================================

def ensure_user(user):
    conn = connect()

    conn.execute(
        """
        INSERT INTO users
        (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
        """,
        (
            user.id,
            user.username,
            user.first_name,
        ),
    )

    conn.commit()
    conn.close()


def user_is_banned(user_id):
    conn = connect()

    row = conn.execute(
        "SELECT is_banned FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    conn.close()

    return bool(row and row["is_banned"])


def save_transaction(user_id, amount, tx_type, description):
    conn = connect()

    conn.execute(
        """
        INSERT INTO transactions
        (user_id, amount, type, description)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            amount,
            tx_type,
            description,
        ),
    )

    conn.commit()
    conn.close()


def change_balance(user_id, amount, description):
    conn = connect()

    row = conn.execute(
        "SELECT diamonds FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    if not row:
        conn.close()
        return None

    old_balance = int(row["diamonds"])
    new_balance = max(0, old_balance + amount)

    actual_change = new_balance - old_balance

    conn.execute(
        """
        UPDATE users
        SET diamonds = ?
        WHERE user_id = ?
        """,
        (
            new_balance,
            user_id,
        ),
    )

    conn.execute(
        """
        INSERT INTO transactions
        (user_id, amount, type, description)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            actual_change,
            "admin_adjustment",
            description,
        ),
    )

    conn.commit()
    conn.close()

    return new_balance


# =========================================================
# BAN CHECK
# =========================================================

async def check_banned(update):
    user = update.effective_user

    if not user:
        return True

    ensure_user(user)

    if user_is_banned(user.id):
        if update.callback_query:
            await update.callback_query.answer(
                "🚫 حساب شما مسدود است.",
                show_alert=True,
            )
        elif update.message:
            await update.message.reply_text(
                "🚫 حساب شما توسط مدیریت مسدود شده است."
            )
        return True

    return False


# =========================================================
# MEMBERSHIP
# =========================================================

async def is_member(context, user_id, channel):
    try:
        member = await context.bot.get_chat_member(
            chat_id=channel,
            user_id=user_id,
        )

        return member.status not in (
            "left",
            "kicked",
        )

    except Exception as e:
        print(f"[MEMBERSHIP ERROR] {channel}: {e}")
        return False


async def check_required_channels(context, user_id):
    for channel in REQUIRED_CHANNELS:
        if not await is_member(
            context,
            user_id,
            channel,
        ):
            return False

    return True


async def require_required_membership(update, context):
    if await check_banned(update):
        return False

    user = update.effective_user

    if await check_required_channels(
        context,
        user.id,
    ):
        return True

    text = (
        "🔐 <b>عضویت اجباری</b>\n\n"
        "برای استفاده از بات باید ابتدا در هر دو کانال زیر عضو شوید:\n\n"
        "📢 @ByteTunnel\n"
        "📢 @membersbyte\n\n"
        "بعد از عضویت روی «✅ بررسی عضویت» بزنید."
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=required_channels_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=required_channels_keyboard(),
        )

    return False


# =========================================================
# START BONUS
# =========================================================

async def give_start_bonus(user_id):
    conn = connect()

    row = conn.execute(
        """
        SELECT start_bonus_received
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    if not row:
        conn.close()
        return 0

    if row["start_bonus_received"]:
        conn.close()
        return 0

    bonus = int(
        get_setting(
            "start_bonus",
            "10",
        )
    )

    conn.execute(
        """
        UPDATE users
        SET diamonds = diamonds + ?,
            start_bonus_received = 1
        WHERE user_id = ?
        """,
        (
            bonus,
            user_id,
        ),
    )

    conn.execute(
        """
        INSERT INTO transactions
        (user_id, amount, type, description)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            bonus,
            "start_bonus",
            "پاداش شروع",
        ),
    )

    conn.commit()
    conn.close()

    return bonus


# =========================================================
# REFERRALS
# =========================================================

async def process_referral(user_id, referrer_id):
    if not referrer_id:
        return

    if user_id == referrer_id:
        return

    conn = connect()

    existing = conn.execute(
        """
        SELECT id
        FROM referrals
        WHERE invited_id = ?
        """,
        (user_id,),
    ).fetchone()

    if existing:
        conn.close()
        return

    inviter = conn.execute(
        """
        SELECT user_id
        FROM users
        WHERE user_id = ?
        """,
        (referrer_id,),
    ).fetchone()

    if not inviter:
        conn.close()
        return

    conn.execute(
        """
        INSERT INTO referrals
        (inviter_id, invited_id, rewarded)
        VALUES (?, ?, 0)
        """,
        (
            referrer_id,
            user_id,
        ),
    )

    conn.execute(
        """
        UPDATE users
        SET referred_by = ?
        WHERE user_id = ?
        """,
        (
            referrer_id,
            user_id,
        ),
    )

    conn.commit()
    conn.close()


async def reward_referral_if_eligible(user_id):
    conn = connect()

    row = conn.execute(
        """
        SELECT inviter_id, rewarded
        FROM referrals
        WHERE invited_id = ?
        """,
        (user_id,),
    ).fetchone()

    if not row or row["rewarded"]:
        conn.close()
        return 0

    inviter_id = row["inviter_id"]

    reward = int(
        get_setting(
            "referral_reward",
            "3",
        )
    )

    conn.execute(
        """
        UPDATE users
        SET diamonds = diamonds + ?,
            referrals = referrals + 1
        WHERE user_id = ?
        """,
        (
            reward,
            inviter_id,
        ),
    )

    conn.execute(
        """
        UPDATE referrals
        SET rewarded = 1
        WHERE invited_id = ?
        """,
        (user_id,),
    )

    conn.execute(
        """
        INSERT INTO transactions
        (user_id, amount, type, description)
        VALUES (?, ?, ?, ?)
        """,
        (
            inviter_id,
            reward,
            "referral",
            f"پاداش زیرمجموعه {user_id}",
        ),
    )

    conn.commit()
    conn.close()

    return reward


# =========================================================
# START
# =========================================================

async def start(update, context):
    user = update.effective_user

    ensure_user(user)

    if user_is_banned(user.id):
        await update.message.reply_text(
            "🚫 حساب شما توسط مدیریت مسدود شده است."
        )
        return

    referrer_id = None

    if context.args:
        try:
            referrer_id = int(
                context.args[0]
            )
        except ValueError:
            pass

    await process_referral(
        user.id,
        referrer_id,
    )

    if not await require_required_membership(
        update,
        context,
    ):
        return

    bonus = await give_start_bonus(
        user.id
    )

    referral_reward = (
        await reward_referral_if_eligible(
            user.id
        )
    )

    text = ""

    if bonus:
        text += (
            "🎉 <b>خوش آمدید!</b>\n\n"
            f"🎁 پاداش شروع: <b>{bonus} 💎</b>\n\n"
        )

    if referral_reward:
        text += (
            f"👥 دعوت شما ثبت شد.\n"
            f"💎 پاداش معرف: {referral_reward} 💎\n\n"
        )

    text += (
        "👑 برای استفاده از قابلیت‌های کانال یا گروه، "
        "بات را ادمین کنید.\n\n"
        "📚 آموزش کامل از بخش «راهنما ⁉️» در دسترس است."
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# REQUIRED CALLBACK
# =========================================================

async def required_membership_callback(update, context):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    ensure_user(user)

    if user_is_banned(user.id):
        await query.message.reply_text(
            "🚫 حساب شما مسدود است."
        )
        return

    if not await check_required_channels(
        context,
        user.id,
    ):
        await query.message.reply_text(
            "❌ هنوز عضویت شما در هر دو کانال تأیید نشده است.",
            reply_markup=required_channels_keyboard(),
        )
        return

    bonus = await give_start_bonus(
        user.id
    )

    if bonus:
        text = (
            "✅ <b>عضویت شما تأیید شد!</b>\n\n"
            f"🎁 {bonus} 💎 پاداش شروع دریافت کردید.\n\n"
            "👑 برای قابلیت‌های کانال یا گروه، بات را ادمین کنید."
        )
    else:
        text = "✅ عضویت شما تأیید شد."

    await query.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# DAILY REWARD
# =========================================================

async def daily_reward(update, context):
    if not await require_required_membership(
        update,
        context,
    ):
        return

    user = update.effective_user

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    conn = connect()

    row = conn.execute(
        """
        SELECT daily_reward_date
        FROM users
        WHERE user_id = ?
        """,
        (user.id,),
    ).fetchone()

    if row and row["daily_reward_date"] == today:
        conn.close()

        await update.message.reply_text(
            "⏳ پاداش امروز را قبلاً دریافت کردی.\n\n"
            "🌙 فردا دوباره برگرد.",
            reply_markup=main_keyboard(),
        )
        return

    reward = int(
        get_setting(
            "daily_reward",
            "5",
        )
    )

    conn.execute(
        """
        UPDATE users
        SET diamonds = diamonds + ?,
            daily_reward_date = ?
        WHERE user_id = ?
        """,
        (
            reward,
            today,
            user.id,
        ),
    )

    conn.execute(
        """
        INSERT INTO transactions
        (user_id, amount, type, description)
        VALUES (?, ?, ?, ?)
        """,
        (
            user.id,
            reward,
            "daily_reward",
            "پاداش روزانه",
        ),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎉 <b>پاداش روزانه دریافت شد!</b>\n\n"
        f"💎 +{reward} الماس",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# MISSIONS
# =========================================================


def get_active_channels():
    conn = connect()

    rows = conn.execute("""
        SELECT
            o.id AS order_id,
            o.user_id AS order_owner_id,
            o.members AS target_members,
            o.status AS order_status,
            o.mission_message_id,
            c.id AS channel_db_id,
            c.channel_id AS telegram_channel_id,
            c.username,
            c.title,
            c.description,
            c.reward,
            c.active AS channel_active
        FROM orders o
        JOIN channels c
            ON CAST(o.channel_id AS INTEGER) = c.id
        WHERE o.status IN ('pending', 'active')
          AND c.active = 1
        ORDER BY o.id ASC
    """).fetchall()

    conn.close()
    return rows


def mission_text(mission):
    conn = connect()

    row = conn.execute("""
        SELECT COUNT(*) AS completed
        FROM mission_tasks
        WHERE order_id = ?
          AND rewarded = 1
    """, (mission["order_id"],)).fetchone()

    conn.close()

    completed = int(row["completed"] or 0)
    target = int(mission["target_members"])

    username = mission["username"] or mission["telegram_channel_id"]

    return (
        "🎯 <b>مأموریت جدید</b>\n\n"
        f"📢 کانال هدف: <b>{html.escape(str(username))}</b>\n"
        f"👤 تعداد موردنیاز: <b>{target}</b>\n"
        f"💎 پاداش هر نفر: <b>{int(mission['reward'])}</b>\n\n"
        f"📊 پیشرفت: <b>{completed}/{target}</b>\n\n"
        "ابتدا وارد کانال هدف شو، سپس روی «بررسی عضویت» بزن."
    )


def mission_keyboard(order_id, username):
    rows = []

    clean = (username or "").strip().lstrip("@")

    if clean:
        rows.append([
            InlineKeyboardButton(
                "🚀 ورود به کانال",
                url=f"https://t.me/{clean}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "✅ بررسی عضویت",
            callback_data=f"mission_check:{order_id}",
        )
    ])

    return InlineKeyboardMarkup(rows)


async def publish_mission(bot, order_id):
    conn = connect()

    mission = conn.execute("""
        SELECT
            o.id AS order_id,
            o.members AS target_members,
            o.status AS order_status,
            o.mission_message_id,
            c.channel_id AS telegram_channel_id,
            c.username,
            c.title,
            c.description,
            c.reward
        FROM orders o
        JOIN channels c
            ON CAST(o.channel_id AS INTEGER) = c.id
        WHERE o.id = ?
    """, (order_id,)).fetchone()

    if not mission:
        order_row = conn.execute(
            "SELECT id, channel_id, status, members, cost FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()

        print(
            f"[MISSION PUBLISH ERROR] "
            f"order={order_id} "
            f"reason=SQL JOIN returned no row "
            f"order_data={dict(order_row) if order_row else None}"
        )

        if order_row:
            channel_row = conn.execute(
                "SELECT id, channel_id, username, title FROM channels WHERE id = ?",
                (order_row["channel_id"],),
            ).fetchone()

            print(
                f"[MISSION CHANNEL DB] "
                f"{dict(channel_row) if channel_row else None}"
            )

        conn.close()
        return None

    if mission["mission_message_id"]:
        message_id = int(mission["mission_message_id"])
        conn.close()
        return message_id

    conn.close()

    try:
        # بررسی مستقیم مقصد مأموریت
        target_chat = await bot.get_chat(MISSION_CHANNEL)

        print(
            f"[MISSION TARGET] "
            f"id={target_chat.id} "
            f"type={target_chat.type} "
            f"title={getattr(target_chat, "title", None)} "
            f"username={getattr(target_chat, "username", None)}"
        )

        # بررسی دسترسی بات به مقصد مأموریت
        me = await bot.get_me()
        member = await bot.get_chat_member(target_chat.id, me.id)

        print(
            f"[MISSION BOT STATUS] "
            f"user={me.username} "
            f"status={member.status}"
        )

        message = await bot.send_message(
            chat_id=target_chat.id,
            text=mission_text(mission),
            parse_mode="HTML",
            reply_markup=mission_keyboard(
                order_id,
                mission["username"],
            ),
        )

        conn = connect()

        conn.execute("""
            UPDATE orders
            SET mission_message_id = ?,
                status = 'active'
            WHERE id = ?
        """, (
            message.message_id,
            order_id,
        ))

        conn.commit()
        conn.close()

        print(
            f"[MISSION PUBLISHED] "
            f"order={order_id} "
            f"message={message.message_id}"
        )

        return message.message_id

    except Exception as e:
        print(
            f"[MISSION PUBLISH ERROR] "
            f"order={order_id} "
            f"target={MISSION_CHANNEL} "
            f"type={type(e).__name__} "
            f"error={e!r}"
        )
        return None


async def update_mission_message(bot, order_id):
    conn = connect()

    mission = conn.execute("""
        SELECT
            o.id AS order_id,
            o.members AS target_members,
            o.status AS order_status,
            o.mission_message_id,
            c.channel_id AS telegram_channel_id,
            c.username,
            c.title,
            c.description,
            c.reward
        FROM orders o
        JOIN channels c
            ON CAST(o.channel_id AS INTEGER) = c.id
        WHERE o.id = ?
    """, (order_id,)).fetchone()

    conn.close()

    if not mission or not mission["mission_message_id"]:
        return

    try:
        await bot.edit_message_text(
            chat_id=MISSION_CHANNEL,
            message_id=int(mission["mission_message_id"]),
            text=mission_text(mission),
            parse_mode="HTML",
            reply_markup=mission_keyboard(
                order_id,
                mission["username"],
            ),
        )
    except Exception as e:
        print("[MISSION UPDATE ERROR]", e)


async def delete_mission_message(bot, order_id):
    conn = connect()

    row = conn.execute("""
        SELECT mission_message_id
        FROM orders
        WHERE id = ?
    """, (order_id,)).fetchone()

    conn.close()

    if not row or not row["mission_message_id"]:
        return

    try:
        await bot.delete_message(
            chat_id=MISSION_CHANNEL,
            message_id=int(row["mission_message_id"]),
        )

        print(
            f"[MISSION DELETED] order={order_id}"
        )

    except Exception as e:
        print("[MISSION DELETE ERROR]", e)


async def mission_check_callback(update, context):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    try:
        order_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer(
            "❌ مأموریت نامعتبر است.",
            show_alert=True,
        )
        return

    conn = connect()

    mission = conn.execute("""
        SELECT
            o.id AS order_id,
            o.user_id AS order_owner_id,
            o.members AS target_members,
            o.status AS order_status,
            c.id AS channel_db_id,
            c.channel_id AS telegram_channel_id,
            c.username,
            c.title,
            c.description,
            c.reward,
            c.active AS channel_active
        FROM orders o
        JOIN channels c
            ON CAST(o.channel_id AS INTEGER) = c.id
        WHERE o.id = ?
    """, (order_id,)).fetchone()

    if not mission:
        conn.close()
        await query.answer(
            "❌ این مأموریت پیدا نشد.",
            show_alert=True,
        )
        return

    if mission["order_status"] == "completed":
        conn.close()
        await query.answer(
            "✅ این مأموریت قبلاً تکمیل شده است.",
            show_alert=True,
        )
        return

    if not mission["channel_active"]:
        conn.close()
        await query.answer(
            "❌ این مأموریت دیگر فعال نیست.",
            show_alert=True,
        )
        return

    existing = conn.execute("""
        SELECT rewarded
        FROM mission_tasks
        WHERE order_id = ?
          AND user_id = ?
    """, (
        order_id,
        user.id,
    )).fetchone()

    conn.close()

    if existing and int(existing["rewarded"]) == 1:
        await query.answer(
            "⚠️ این مأموریت را قبلاً انجام داده‌ای.",
            show_alert=True,
        )
        return

    try:
        member = await context.bot.get_chat_member(
            mission["telegram_channel_id"],
            user.id,
        )

        is_joined = member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as e:
        print("[MISSION CHECK ERROR]", e)
        is_joined = False

    if not is_joined:
        await query.answer(
            "❌ هنوز عضو کانال نشده‌ای.",
            show_alert=True,
        )
        return

    joined_at = datetime.now(timezone.utc).isoformat()

    conn = connect()

    try:
        conn.execute("""
            INSERT OR IGNORE INTO mission_tasks
            (
                order_id,
                channel_id,
                user_id,
                rewarded,
                joined_at,
                retention_completed,
                penalty_applied
            )
            VALUES (?, ?, ?, 1, ?, 0, 0)
        """, (
            order_id,
            mission["channel_db_id"],
            user.id,
            joined_at,
        ))

        inserted = conn.execute("""
            SELECT rewarded
            FROM mission_tasks
            WHERE order_id = ?
              AND user_id = ?
        """, (
            order_id,
            user.id,
        )).fetchone()

        if not inserted or int(inserted["rewarded"]) != 1:
            conn.rollback()
            conn.close()

            await query.answer(
                "❌ ثبت مأموریت انجام نشد.",
                show_alert=True,
            )
            return

        reward = int(mission["reward"])

        conn.execute("""
            UPDATE users
            SET diamonds = diamonds + ?
            WHERE user_id = ?
        """, (
            reward,
            user.id,
        ))

        conn.execute("""
            INSERT INTO transactions
            (user_id, amount, type, description)
            VALUES (?, ?, ?, ?)
        """, (
            user.id,
            reward,
            "channel_join",
            f"مأموریت سفارش #{order_id}",
        ))

        progress = conn.execute("""
            SELECT COUNT(*) AS completed
            FROM mission_tasks
            WHERE order_id = ?
              AND rewarded = 1
        """, (order_id,)).fetchone()

        completed = int(progress["completed"] or 0)
        target = int(mission["target_members"])

        mission_completed = completed >= target

        if mission_completed:
            conn.execute("""
                UPDATE orders
                SET status = 'completed'
                WHERE id = ?
            """, (order_id,))

        else:
            conn.execute("""
                UPDATE orders
                SET status = 'active'
                WHERE id = ?
                  AND status = 'pending'
            """, (order_id,))

        conn.commit()
        conn.close()

    except Exception as e:
        conn.rollback()
        conn.close()

        print("[MISSION REWARD ERROR]", e)

        await query.answer(
            "❌ خطایی هنگام ثبت مأموریت رخ داد.",
            show_alert=True,
        )
        return

    if mission_completed:

        await delete_mission_message(
            context.bot,
            order_id,
        )

        await query.answer(
            f"🎉 مأموریت کامل شد! {completed}/{target}",
            show_alert=True,
        )

        try:
            await context.bot.send_message(
                chat_id=mission["order_owner_id"],
                text=(
                    "🎉 <b>سفارش شما تکمیل شد!</b>\n\n"
                    f"🆔 سفارش: <code>#{order_id}</code>\n"
                    f"👥 تعداد تکمیل‌شده: <b>{completed}/{target}</b>\n"
                    "✅ وضعیت: تکمیل شده"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            print("[ORDER OWNER NOTIFY ERROR]", e)

    else:

        await update_mission_message(
            context.bot,
            order_id,
        )

        await query.answer(
            f"✅ مأموریت ثبت شد!\n📊 {completed}/{target}",
            show_alert=True,
        )


async def check_retention(bot):
    conn = connect()

    rows = conn.execute("""
        SELECT
            mt.id,
            mt.order_id,
            mt.user_id,
            mt.joined_at,
            mt.penalty_applied,
            c.channel_id AS telegram_channel_id
        FROM mission_tasks mt
        JOIN channels c
            ON c.id = mt.channel_id
        WHERE mt.rewarded = 1
          AND mt.joined_at IS NOT NULL
          AND mt.penalty_applied = 0
          AND mt.retention_completed = 0
    """).fetchall()

    now = datetime.now(timezone.utc)

    for row in rows:

        try:
            joined = datetime.fromisoformat(
                row["joined_at"]
            )

            if joined.tzinfo is None:
                joined = joined.replace(
                    tzinfo=timezone.utc
                )

            age = (
                now - joined
            ).total_seconds()

            if age >= RETENTION_SECONDS:

                conn.execute("""
                    UPDATE mission_tasks
                    SET retention_completed = 1
                    WHERE id = ?
                """, (
                    row["id"],
                ))

                continue

            try:
                member = await bot.get_chat_member(
                    row["telegram_channel_id"],
                    row["user_id"],
                )

                still_joined = member.status in (
                    "member",
                    "administrator",
                    "creator",
                )

            except Exception as e:
                print(
                    "[RETENTION CHECK ERROR]",
                    row["user_id"],
                    e,
                )
                continue

            if still_joined:
                continue

            current = conn.execute("""
                SELECT diamonds
                FROM users
                WHERE user_id = ?
            """, (
                row["user_id"],
            )).fetchone()

            balance = (
                int(current["diamonds"])
                if current else 0
            )

            penalty = min(
                MISSION_PENALTY,
                max(balance, 0),
            )

            new_balance = balance - penalty

            conn.execute("""
                UPDATE users
                SET diamonds = ?
                WHERE user_id = ?
            """, (
                new_balance,
                row["user_id"],
            ))

            if penalty > 0:

                conn.execute("""
                    INSERT INTO transactions
                    (
                        user_id,
                        amount,
                        type,
                        description
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    row["user_id"],
                    -penalty,
                    "early_leave_penalty",
                    f"جریمه خروج زودهنگام از مأموریت #{row['order_id']}",
                ))

            conn.execute("""
                UPDATE mission_tasks
                SET penalty_applied = 1,
                    retention_completed = 1
                WHERE id = ?
            """, (
                row["id"],
            ))

            try:
                await bot.send_message(
                    chat_id=row["user_id"],
                    text=(
                        "⚠️ <b>کسر الماس</b>\n\n"
                        "قبل از کامل شدن ۴ روز از "
                        "کانال مأموریت خارج شدی.\n"
                        f"💎 کسرشده: <b>{penalty}</b>\n"
                        f"💎 موجودی فعلی: <b>{new_balance}</b>"
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:
                print(
                    "[PENALTY NOTIFY ERROR]",
                    row["user_id"],
                    e,
                )

        except Exception as e:
            print(
                "[RETENTION ERROR]",
                row["id"],
                e,
            )

    conn.commit()
    conn.close()


async def retention_job(context):
    try:
        await check_retention(context.bot)
    except Exception as e:
        print("[RETENTION JOB ERROR]", e)


async def account(update, context):
    if not await require_required_membership(
        update,
        context,
    ):
        return

    user = update.effective_user

    conn = connect()

    row = conn.execute(
        """
        SELECT diamonds, referrals, is_banned
        FROM users
        WHERE user_id = ?
        """,
        (user.id,),
    ).fetchone()

    conn.close()

    diamonds = row["diamonds"] if row else 0
    referrals = row["referrals"] if row else 0

    await update.message.reply_text(
        "🔐 <b>حساب کاربری</b>\n\n"
        f"🆔 آیدی: <code>{user.id}</code>\n"
        f"👤 نام: {html.escape(user.first_name or '-')}\n"
        f"💎 موجودی: <b>{diamonds}</b>\n"
        f"👥 زیرمجموعه موفق: <b>{referrals}</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# REFERRAL MENU
# =========================================================

async def referral_menu(update, context):
    if not await require_required_membership(
        update,
        context,
    ):
        return

    user = update.effective_user

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start={user.id}"
    )

    conn = connect()

    row = conn.execute(
        """
        SELECT referrals
        FROM users
        WHERE user_id = ?
        """,
        (user.id,),
    ).fetchone()

    conn.close()

    count = row["referrals"] if row else 0
    reward = int(
        get_setting(
            "referral_reward",
            "3",
        )
    )

    await update.message.reply_text(
        "👥 <b>زیرمجموعه‌گیری</b>\n\n"
        f"👤 تعداد دعوت موفق: <b>{count}</b>\n"
        f"💎 پاداش هر دعوت: <b>{reward}</b>\n\n"
        "🔗 لینک اختصاصی شما:\n"
        f"<code>{link}</code>\n\n"
        "لینک را برای دوستانت ارسال کن.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# HELP
# =========================================================

async def help_menu(update, context):
    if not await require_required_membership(
        update,
        context,
    ):
        return

    await update.message.reply_text(
        "📚 <b>راهنمای کامل</b>\n\n"
        "💎 <b>دریافت الماس</b>\n"
        "هر روز پاداش روزانه بگیر و مأموریت‌های عضویت را انجام بده.\n\n"
        "🚀 <b>سفارش ممبر</b>\n"
        "کانال خودت را ثبت کن، یکی از پلن‌ها را انتخاب کن و سفارش بده.\n\n"
        "👥 <b>زیرمجموعه</b>\n"
        "لینک دعوت اختصاصی خودت را برای دوستانت بفرست.\n\n"
        "👑 <b>ادمین کردن بات</b>\n"
        "1️⃣ وارد کانال یا گروه خودت شو.\n"
        "2️⃣ بخش مدیریت / Administrators را باز کن.\n"
        "3️⃣ بات را Add کن.\n"
        "4️⃣ دسترسی‌های لازم را فعال کن.\n"
        "5️⃣ دوباره به بات برگرد و عملیات را ادامه بده.\n\n"
        "⚠️ برای بررسی عضویت و مدیریت کانال، بات باید دسترسی لازم را داشته باشد.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ORDERS
# =========================================================

def order_plan_keyboard():
    rows = []

    for members in ["5", "10", "15", "20", "60", "100"]:
        price = int(
            get_setting(
                PRICE_KEYS[members],
                PRICE_DEFAULTS[PRICE_KEYS[members]],
            )
        )

        rows.append([
            f"{members} نفر = {price} 💎"
        ])

    return ReplyKeyboardMarkup(
        rows + [
            ["🔙 بازگشت"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


async def order_menu(update, context):
    if not await require_required_membership(
        update,
        context,
    ):
        return

    context.user_data.pop(
        "order_channel",
        None,
    )

    await update.message.reply_text(
        "🚀 <b>سفارش ممبر</b>\n\n"
        "پلن موردنظر را انتخاب کن:",
        parse_mode="HTML",
        reply_markup=order_plan_keyboard(),
    )

    context.user_data["order_state"] = "choose_plan"


async def handle_order_plan(update, context, text):
    if text == "🔙 بازگشت":
        context.user_data.pop(
            "order_state",
            None,
        )

        await update.message.reply_text(
            "🏠 منوی اصلی",
            reply_markup=main_keyboard(),
        )
        return True

    members = None

    for count in PRICE_KEYS:
        if text.startswith(count + " نفر"):
            members = int(count)
            break

    if not members:
        return False

    key = PRICE_KEYS[str(members)]

    price = int(
        get_setting(
            key,
            PRICE_DEFAULTS[key],
        )
    )

    context.user_data["order_members"] = members
    context.user_data["order_cost"] = price
    context.user_data["order_state"] = "channel"

    await update.message.reply_text(
        f"📦 پلن انتخاب شد:\n\n"
        f"👤 تعداد: {members} نفر\n"
        f"💎 هزینه: {price}\n\n"
        "🆔 حالا آیدی کانال را بفرست.\n"
        "مثال:\n"
        "<code>@MyChannel</code>",
        parse_mode="HTML",
        reply_markup=admin_cancel_keyboard(),
    )

    return True


async def handle_order_channel(update, context, text):
    if text == "❌ لغو":
        context.user_data.clear()

        await update.message.reply_text(
            "❌ سفارش لغو شد.",
            reply_markup=main_keyboard(),
        )
        return True

    channel_id = text.strip()

    if not channel_id:
        return True

    try:
        chat = await context.bot.get_chat(
            channel_id
        )

        bot_member = await context.bot.get_chat_member(
            chat.id,
            context.bot.id,
        )

        if bot_member.status not in (
            "administrator",
            "creator",
        ):
            await update.message.reply_text(
                "❌ بات در این کانال ادمین نیست.\n\n"
                "ابتدا بات را ادمین کن و دوباره آیدی کانال را بفرست.",
                reply_markup=admin_cancel_keyboard(),
            )
            return True

        title = chat.title or channel_id
        username = chat.username

        conn = connect()

        existing = conn.execute(
            """
            SELECT id
            FROM channels
            WHERE channel_id = ?
            """,
            (
                str(chat.id),
            ),
        ).fetchone()

        if existing:
            channel_db_id = existing["id"]
        else:
            conn.execute(
                """
                INSERT INTO channels
                (
                    channel_id,
                    username,
                    title,
                    description,
                    reward,
                    active,
                    added_by
                )
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    str(chat.id),
                    f"@{username}" if username else None,
                    title,
                    "",
                    1,
                    update.effective_user.id,
                ),
            )

            channel_db_id = conn.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0]

        conn.commit()
        conn.close()

        members = context.user_data["order_members"]
        cost = context.user_data["order_cost"]

        conn = connect()

        row = conn.execute(
            """
            SELECT diamonds
            FROM users
            WHERE user_id = ?
            """,
            (update.effective_user.id,),
        ).fetchone()

        balance = int(row["diamonds"]) if row else 0

        if balance < cost:
            conn.close()

            context.user_data.clear()

            await update.message.reply_text(
                f"❌ موجودی کافی نیست.\n\n"
                f"💎 موجودی: {balance}\n"
                f"💰 هزینه: {cost}\n"
                f"📉 کمبود: {cost - balance}",
                reply_markup=main_keyboard(),
            )
            return True

        conn.execute(
            """
            UPDATE users
            SET diamonds = diamonds - ?
            WHERE user_id = ?
            """,
            (
                cost,
                update.effective_user.id,
            ),
        )

        conn.execute(
            """
            INSERT INTO orders
            (user_id, channel_id, members, cost, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                update.effective_user.id,
                channel_db_id,
                members,
                cost,
            ),
        )

        order_id = conn.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO transactions
            (user_id, amount, type, description)
            VALUES (?, ?, ?, ?)
            """,
            (
                update.effective_user.id,
                -cost,
                "order",
                f"سفارش {members} ممبر برای {title}",
            ),
        )

        conn.commit()
        conn.close()

        # انتشار مأموریت در @membersbyte
        mission_message_id = await publish_mission(
            context.bot,
            order_id,
        )

        # اگر انتشار مأموریت شکست خورد، سفارش لغو و هزینه برگردانده شود
        if not mission_message_id:
            refund_conn = connect()

            refund_conn.execute(
                """
                UPDATE orders
                SET status = 'cancelled'
                WHERE id = ?
                """,
                (order_id,),
            )

            refund_conn.execute(
                """
                UPDATE users
                SET diamonds = diamonds + ?
                WHERE user_id = ?
                """,
                (
                    cost,
                    update.effective_user.id,
                ),
            )

            refund_conn.execute(
                """
                INSERT INTO transactions
                (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
                """,
                (
                    update.effective_user.id,
                    cost,
                    "order_refund",
                    f"بازگشت هزینه سفارش لغوشده #{order_id}",
                ),
            )

            refund_conn.commit()
            refund_conn.close()

            context.user_data.clear()

            await update.message.reply_text(
                "❌ <b>انتشار مأموریت انجام نشد.</b>\n\n"
                "هزینه سفارش به حساب شما برگشت داده شد.\n"
                f"💎 مبلغ برگشتی: <b>{cost}</b>",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )

            return True

        context.user_data.clear()

        await update.message.reply_text(
            "✅ <b>سفارش ثبت شد!</b>\n\n"
            f"🆔 سفارش: <code>#{order_id}</code>\n"
            f"📢 کانال: {html.escape(title)}\n"
            f"👤 تعداد: {members}\n"
            f"💎 هزینه: {cost}\n"
            "📌 وضعیت: فعال\n\n"
            "📢 مأموریت در کانال @membersbyte منتشر شد.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )

        return True

    except Exception as e:
        print("[ORDER ERROR]", e)

        await update.message.reply_text(
            "❌ کانال پیدا نشد یا دسترسی بات کافی نیست.\n\n"
            "آیدی صحیح کانال را ارسال کن.",
            reply_markup=admin_cancel_keyboard(),
        )

        return True


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id):
    return user_id == ADMIN_ID


async def admin_start(update, context):
    user = update.effective_user

    if not is_admin(user.id):
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )
        return

    context.user_data.clear()

    await update.message.reply_text(
        "👑 <b>پنل مدیریت</b>\n\n"
        "یکی از گزینه‌های زیر را انتخاب کن:",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def admin_stats(update, context):
    conn = connect()

    users = conn.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    banned = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE is_banned = 1"
    ).fetchone()["c"]

    diamonds = conn.execute(
        "SELECT COALESCE(SUM(diamonds),0) c FROM users"
    ).fetchone()["c"]

    channels = conn.execute(
        "SELECT COUNT(*) c FROM channels WHERE active = 1"
    ).fetchone()["c"]

    orders = conn.execute(
        "SELECT COUNT(*) c FROM orders"
    ).fetchone()["c"]

    pending = conn.execute(
        "SELECT COUNT(*) c FROM orders WHERE status = 'pending'"
    ).fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        "📊 <b>آمار سیستم</b>\n\n"
        f"👥 کل کاربران: <b>{users}</b>\n"
        f"🚫 کاربران بن‌شده: <b>{banned}</b>\n"
        f"💎 مجموع الماس کاربران: <b>{diamonds}</b>\n"
        f"📢 کانال‌های فعال: <b>{channels}</b>\n"
        f"📦 کل سفارشات: <b>{orders}</b>\n"
        f"⏳ سفارشات در انتظار: <b>{pending}</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def admin_users(update, context):
    conn = connect()

    rows = conn.execute(
        """
        SELECT user_id, first_name, username, diamonds, referrals, is_banned
        FROM users
        ORDER BY created_at DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "📭 کاربری وجود ندارد.",
            reply_markup=admin_keyboard(),
        )
        return

    lines = ["👥 <b>آخرین کاربران</b>\n"]

    for row in rows:
        status = "🚫" if row["is_banned"] else "🟢"
        name = html.escape(
            row["first_name"] or "-"
        )

        lines.append(
            f"{status} <code>{row['user_id']}</code> | "
            f"{name} | 💎 {row['diamonds']} | "
            f"👥 {row['referrals']}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def admin_search_prompt(update, context):
    context.user_data["admin_state"] = "search"

    await update.message.reply_text(
        "🔎 آیدی عددی کاربر را بفرست:",
        reply_markup=admin_cancel_keyboard(),
    )


async def admin_balance_prompt(update, context):
    context.user_data["admin_state"] = "balance_user"

    await update.message.reply_text(
        "💎 آیدی کاربر را بفرست:",
        reply_markup=admin_cancel_keyboard(),
    )


async def admin_ban_prompt(update, context):
    context.user_data["admin_state"] = "ban_user"

    await update.message.reply_text(
        "🚫 آیدی کاربر را بفرست:",
        reply_markup=admin_cancel_keyboard(),
    )


async def admin_add_channel_prompt(update, context):
    context.user_data["admin_state"] = "add_channel"

    await update.message.reply_text(
        "➕ اطلاعات کانال را به این شکل بفرست:\n\n"
        "<code>@username | نام کانال | توضیحات | پاداش</code>\n\n"
        "مثال:\n"
        "<code>@test | Test Channel | توضیحات کانال | 2</code>",
        parse_mode="HTML",
        reply_markup=admin_cancel_keyboard(),
    )


async def admin_rewards_menu(update, context):
    await update.message.reply_text(
        "💰 <b>مدیریت پاداش‌ها</b>\n\n"
        f"🎁 پاداش شروع: {get_setting('start_bonus','10')}\n"
        f"🌙 پاداش روزانه: {get_setting('daily_reward','5')}\n"
        f"👥 پاداش دعوت: {get_setting('referral_reward','3')}\n"
        f"📢 پاداش عضویت: {get_setting('channel_join_reward','2')}\n\n"
        "برای تغییر یکی از موارد، این فرمت را بفرست:\n"
        "<code>start 10</code>\n"
        "<code>daily 5</code>\n"
        "<code>referral 3</code>\n"
        "<code>join 2</code>",
        parse_mode="HTML",
        reply_markup=admin_cancel_keyboard(),
    )

    context.user_data["admin_state"] = "rewards"


async def admin_prices_menu(update, context):
    text = "💵 <b>قیمت پلن‌ها</b>\n\n"

    for members in PRICE_KEYS:
        key = PRICE_KEYS[members]

        price = get_setting(
            key,
            str(PRICE_DEFAULTS[key]),
        )

        text += f"👤 {members} نفر = 💎 {price}\n"

    text += (
        "\nبرای تغییر:\n"
        "<code>5 10</code>\n"
        "<code>100 120</code>"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=admin_cancel_keyboard(),
    )

    context.user_data["admin_state"] = "prices"


async def admin_channels(update, context):
    conn = connect()

    rows = conn.execute(
        """
        SELECT id, channel_id, username, title, reward, active
        FROM channels
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "📭 کانالی ثبت نشده.",
            reply_markup=admin_keyboard(),
        )
        return

    lines = ["📋 <b>کانال‌ها</b>\n"]

    for row in rows:
        status = "🟢" if row["active"] else "🔴"

        lines.append(
            f"{status} #{row['id']} | "
            f"{html.escape(str(row['title'] or '-'))}\n"
            f"🆔 {row['username'] or row['channel_id']} | "
            f"💎 {row['reward']}"
        )

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def admin_orders(update, context):
    conn = connect()

    rows = conn.execute(
        """
        SELECT
            orders.id,
            orders.user_id,
            orders.members,
            orders.cost,
            orders.status,
            channels.title
        FROM orders
        LEFT JOIN channels
        ON channels.id = orders.channel_id
        ORDER BY orders.id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "📭 سفارشی وجود ندارد.",
            reply_markup=admin_keyboard(),
        )
        return

    lines = ["📦 <b>آخرین سفارشات</b>\n"]

    for row in rows:
        lines.append(
            f"🆔 #{row['id']}\n"
            f"👤 کاربر: <code>{row['user_id']}</code>\n"
            f"📢 {html.escape(str(row['title'] or '-'))}\n"
            f"👥 {row['members']} | 💎 {row['cost']}\n"
            f"📌 {row['status']}"
        )

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ADMIN STATE HANDLER
# =========================================================

async def handle_admin_state(update, context, text):
    user = update.effective_user

    if not is_admin(user.id):
        return False

    state = context.user_data.get(
        "admin_state"
    )

    if not state:
        return False

    if text in (
        "❌ لغو",
        "🏠 منوی ادمین",
    ):
        context.user_data.clear()

        await update.message.reply_text(
            "👑 پنل ادمین",
            reply_markup=admin_keyboard(),
        )

        return True

    if state == "search":
        try:
            user_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ آیدی باید عددی باشد."
            )
            return True

        conn = connect()

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        conn.close()

        if not row:
            await update.message.reply_text(
                "❌ کاربر پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
            context.user_data.clear()
            return True

        await update.message.reply_text(
            "🔎 <b>اطلاعات کاربر</b>\n\n"
            f"🆔 <code>{row['user_id']}</code>\n"
            f"👤 {html.escape(row['first_name'] or '-')}\n"
            f"🔗 @{row['username'] or '-'}\n"
            f"💎 {row['diamonds']}\n"
            f"👥 {row['referrals']}\n"
            f"🚫 بن: {'بله' if row['is_banned'] else 'خیر'}",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )

        context.user_data.clear()
        return True

    if state == "balance_user":
        try:
            user_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ آیدی باید عددی باشد."
            )
            return True

        context.user_data["target_user"] = user_id
        context.user_data["admin_state"] = "balance_amount"

        await update.message.reply_text(
            "💎 مقدار تغییر را بفرست.\n\n"
            "مثال:\n"
            "<code>+50</code>\n"
            "<code>-20</code>",
            parse_mode="HTML",
            reply_markup=admin_cancel_keyboard(),
        )

        return True

    if state == "balance_amount":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ مقدار باید عددی باشد."
            )
            return True

        target = context.user_data.get(
            "target_user"
        )

        new_balance = change_balance(
            target,
            amount,
            "تغییر دستی توسط ادمین",
        )

        if new_balance is None:
            await update.message.reply_text(
                "❌ کاربر پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
        else:
            await update.message.reply_text(
                f"✅ موجودی تغییر کرد.\n\n"
                f"👤 <code>{target}</code>\n"
                f"💎 موجودی جدید: <b>{new_balance}</b>",
                parse_mode="HTML",
                reply_markup=admin_keyboard(),
            )

        context.user_data.clear()
        return True

    if state == "ban_user":
        try:
            user_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ آیدی باید عددی باشد."
            )
            return True

        conn = connect()

        row = conn.execute(
            """
            SELECT is_banned
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        if not row:
            conn.close()

            await update.message.reply_text(
                "❌ کاربر پیدا نشد.",
                reply_markup=admin_keyboard(),
            )

            context.user_data.clear()
            return True

        new_status = 0 if row["is_banned"] else 1

        conn.execute(
            """
            UPDATE users
            SET is_banned = ?
            WHERE user_id = ?
            """,
            (
                new_status,
                user_id,
            ),
        )

        conn.commit()
        conn.close()

        await update.message.reply_text(
            (
                "🚫 کاربر بن شد."
                if new_status
                else "✅ کاربر آنبن شد."
            ),
            reply_markup=admin_keyboard(),
        )

        context.user_data.clear()
        return True

    if state == "add_channel":
        parts = [x.strip() for x in text.split("|")]

        if len(parts) != 4:
            await update.message.reply_text(
                "❌ فرمت اشتباه است.\n\n"
                "<code>@username | نام | توضیحات | 2</code>",
                parse_mode="HTML",
            )
            return True

        username, title, description, reward = parts

        if not username:
            await update.message.reply_text(
                "❌ یوزرنیم کانال وارد نشده است."
            )
            return True

        if not username.startswith("@"):
            username = "@" + username

        try:
            reward = int(reward)
            if reward < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ پاداش باید یک عدد صفر یا بیشتر باشد."
            )
            return True

        try:
            # دریافت اطلاعات واقعی کانال
            chat = await context.bot.get_chat(username)

            # فقط کانال قابل ثبت است
            if getattr(chat, "type", None) != "channel":
                await update.message.reply_text(
                    "❌ این آیدی مربوط به یک کانال نیست."
                )
                return True

            # بررسی دسترسی خود بات در کانال
            bot_member = await context.bot.get_chat_member(
                chat.id,
                context.bot.id,
            )

            if bot_member.status not in ("administrator", "creator"):
                await update.message.reply_text(
                    "❌ کانال تأیید نشد.\n\n"
                    "🤖 بات باید داخل کانال "
                    "<b>Administrator</b> یا <b>Creator</b> باشد.\n"
                    "بعد از ادمین کردن بات دوباره تلاش کن.",
                    parse_mode="HTML",
                )
                return True

            # اطلاعات واقعی کانال
            actual_username = getattr(chat, "username", None)

            if actual_username:
                actual_username = "@" + actual_username
            else:
                actual_username = username

            actual_title = getattr(chat, "title", None) or title

            conn = connect()

            conn.execute(
                """
                INSERT INTO channels
                (
                    channel_id,
                    username,
                    title,
                    description,
                    reward,
                    active,
                    added_by
                )
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(channel_id)
                DO UPDATE SET
                    username = excluded.username,
                    title = excluded.title,
                    description = excluded.description,
                    reward = excluded.reward,
                    active = 1,
                    added_by = excluded.added_by
                """,
                (
                    str(chat.id),
                    actual_username,
                    actual_title,
                    description,
                    reward,
                    ADMIN_ID,
                ),
            )

            conn.commit()
            conn.close()

            await update.message.reply_text(
                "✅ <b>کانال با موفقیت فعال شد.</b>\n\n"
                f"📢 <b>{html.escape(str(actual_title))}</b>\n"
                f"🆔 <code>{html.escape(str(actual_username))}</code>\n"
                f"💎 پاداش: <b>{reward}</b> الماس\n\n"
                "🟢 وضعیت: فعال\n"
                "🤖 دسترسی بات: Administrator",
                parse_mode="HTML",
                reply_markup=admin_keyboard(),
            )

            context.user_data.clear()
            return True

        except Exception as e:
            print("[ADD CHANNEL ERROR]", repr(e))

            await update.message.reply_text(
                "❌ <b>کانال تأیید نشد.</b>\n\n"
                "مطمئن شو آیدی کانال صحیح است و بات داخل کانال "
                "به عنوان Administrator اضافه شده است.",
                parse_mode="HTML",
            )

            return True

    if state == "rewards":
        parts = text.split()

        if len(parts) != 2:
            await update.message.reply_text(
                "❌ مثال: <code>daily 5</code>",
                parse_mode="HTML",
            )
            return True

        aliases = {
            "start": "start_bonus",
            "daily": "daily_reward",
            "referral": "referral_reward",
            "join": "channel_join_reward",
        }

        key = aliases.get(parts[0].lower())

        if not key:
            await update.message.reply_text(
                "❌ گزینه نامعتبر."
            )
            return True

        try:
            value = int(parts[1])

            if value < 0:
                raise ValueError

        except ValueError:
            await update.message.reply_text(
                "❌ مقدار باید عدد مثبت باشد."
            )
            return True

        set_setting(
            key,
            str(value),
        )

        await update.message.reply_text(
            f"✅ مقدار <code>{key}</code> شد: <b>{value}</b>",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )

        context.user_data.clear()
        return True

    if state == "prices":
        parts = text.split()

        if len(parts) != 2:
            await update.message.reply_text(
                "❌ مثال: <code>100 120</code>",
                parse_mode="HTML",
            )
            return True

        members, price = parts

        if members not in PRICE_KEYS:
            await update.message.reply_text(
                "❌ تعداد اعضا نامعتبر است."
            )
            return True

        try:
            price = int(price)

            if price < 0:
                raise ValueError

        except ValueError:
            await update.message.reply_text(
                "❌ قیمت باید عددی باشد."
            )
            return True

        set_setting(
            PRICE_KEYS[members],
            str(price),
        )

        await update.message.reply_text(
            f"✅ قیمت {members} نفر شد: 💎 {price}",
            reply_markup=admin_keyboard(),
        )

        context.user_data.clear()
        return True

    return False


# =========================================================
# ADMIN MENU ROUTER
# =========================================================

async def admin_menu_router(update, context, text):
    user = update.effective_user

    if not is_admin(user.id):
        return False

    if await handle_admin_state(
        update,
        context,
        text,
    ):
        return True

    if text == "📊 آمار":
        await admin_stats(update, context)
        return True

    if text == "👥 مدیریت کاربران":
        await admin_users(update, context)
        return True

    if text == "💎 مدیریت الماس":
        await admin_balance_prompt(update, context)
        return True

    if text == "🚫 بن / آنبن":
        await admin_ban_prompt(update, context)
        return True

    if text == "📢 مدیریت کانال‌ها":
        await admin_channels(update, context)
        return True

    if text == "➕ افزودن کانال":
        await admin_add_channel_prompt(update, context)
        return True

    if text == "💰 مدیریت پاداش‌ها":
        await admin_rewards_menu(update, context)
        return True

    if text == "💵 مدیریت قیمت‌ها":
        await admin_prices_menu(update, context)
        return True

    if text == "🔎 جستجوی کاربر":
        await admin_search_prompt(update, context)
        return True

    if text == "📋 لیست کانال‌ها":
        await admin_channels(update, context)
        return True

    if text == "📦 سفارشات":
        await admin_orders(update, context)
        return True

    if text == "🏠 منوی اصلی":
        context.user_data.clear()

        await update.message.reply_text(
            "🏠 منوی اصلی",
            reply_markup=main_keyboard(),
        )
        return True

    return False


# =========================================================
# MAIN MENU
# =========================================================

async def menu_handler(update, context):
    text = update.message.text if update.message else ""
    user = update.effective_user

    ensure_user(user)

    # ADMIN
    if is_admin(user.id):
        if await admin_menu_router(
            update,
            context,
            text,
        ):
            return

        if text == "👑 پنل مدیریت":
            await admin_start(update, context)
            return

    # ORDER STATE
    if context.user_data.get(
        "order_state"
    ) == "choose_plan":

        if await handle_order_plan(
            update,
            context,
            text,
        ):
            return

    if context.user_data.get(
        "order_state"
    ) == "channel":

        if await handle_order_channel(
            update,
            context,
            text,
        ):
            return

    # USER MENU
    if text == "💎 دریافت الماس رایگان 💎":
        await daily_reward(
            update,
            context,
        )

    elif text == "🚀 سفارش ممبر 🚀":
        await order_menu(
            update,
            context,
        )

    elif text == "🔐 حساب کاربری 🔐":
        await account(
            update,
            context,
        )
    elif text == "👥 زیر مجموعه گیری 👥":
        await referral_menu(
            update,
            context,
        )

    elif text == "📚 راهنما ⁉️":
        await help_menu(
            update,
            context,
        )


# =========================================================
# ADMIN COMMAND
# =========================================================

async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )
        return

    await admin_start(
        update,
        context,
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است."
        )

    if BOT_TOKEN == "توکن_بات_اینجا":
        raise RuntimeError(
            "❌ ابتدا BOT_TOKEN واقعی بات را داخل .env قرار بده."
        )

    init_db()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            required_membership_callback,
            pattern=r"^check_required$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            mission_check_callback,
            pattern=r"^mission_check:\d+$",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            menu_handler,
        )
    )

    if app.job_queue:
        app.job_queue.run_repeating(
            retention_job,
            interval=1800,
            first=60,
        )
        print("🛡️ Retention monitor: ON")
    else:
        print("⚠️ JobQueue unavailable")

    print("======================================")
    print("🤖 MemberGetterBot is running...")
    print(f"👑 ADMIN_ID: {ADMIN_ID}")
    print("💎 Diamonds system: ON")
    print("👥 Referral system: ON")
    print("📢 Missions system: ON")
    print("🚀 Orders system: ON")
    print("👑 Admin panel: ON")
    print("======================================")

    app.run_polling()


if __name__ == "__main__":
    main()

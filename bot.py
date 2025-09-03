import os
import re
import json
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ApplicationBuilder,
)

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ---------- ENV ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]
USER_ID = os.environ["USER_ID"]  # admin/chat id for reminders
TZ_NAME = os.environ.get("TZ", "UTC")  # e.g. "Asia/Bangkok"
TZ = ZoneInfo(TZ_NAME)

# ---------- Google Sheets ----------
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(os.environ["GOOGLE_CREDENTIALS"]), scope)
client = gspread.authorize(creds)

# Sheet settings (edit if your worksheet/tab name differs)
PAYMENT_SHEET_TITLE = "Form Responses"
APPLICATION_SHEET_TITLE = "Form Responses 1"

# Replace with your actual Google Sheet IDs
PAYMENT_SHEET_ID = "1TGTmAXV2X9U0r3PBEq41_LV6BpSE5QSJnWaszG0DFJk"
APPLICATION_SHEET_ID = "1RHViIWFcg005F52mfv6eFCDZo6U2ROiLbfn8PJkjk2Y"

# Open both worksheets
payment_ws = client.open_by_key(PAYMENT_SHEET_ID).worksheet(PAYMENT_SHEET_TITLE)
application_ws = client.open_by_key(APPLICATION_SHEET_ID).worksheet(APPLICATION_SHEET_TITLE)


# ---------- Helpers ----------
def parse_date_flexible(s: str):
    if not s:
        return None
    s = str(s).strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        return datetime(year, month, 1, tzinfo=TZ)
    try:
        dt = date_parser.parse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        else:
            dt = dt.astimezone(TZ)
        return dt
    except Exception:
        logging.warning(f"Could not parse date string: {s}")
        return None

def parse_duration_months(comment: str) -> int:
    if not comment:
        return 1
    comment = str(comment).lower()
    m = re.search(r"(\d+)\s*(?:month|months|mo|mth|mnt)\b", comment)
    if m:
        months = int(m.group(1))
        return max(1, min(months, 60))
    return 1

def pick_start_date(record: dict):
    ts = record.get("Timestamp") or record.get("timestamp")
    pay = record.get("Payment Month") or record.get("Payment Month ") or record.get("Pay Month")
    pay_dt = parse_date_flexible(pay) if pay else None
    ts_dt = parse_date_flexible(ts) if ts else None
    return pay_dt or ts_dt

def get_name(record: dict) -> str:
    return (
        record.get("Member Name")
        or record.get("Name")
        or record.get("Full Name")
        or record.get("Telegram User Name")
        or "Member"
    )

def get_comment(record: dict) -> str:
    return record.get("Any additional comments?") or record.get("Any additional comment?") or ""

def compute_status(record: dict):
    start_date = pick_start_date(record)
    if not start_date:
        return None

    months = parse_duration_months(get_comment(record))
    expiry_date = start_date + relativedelta(months=months)

    now = datetime.now(TZ)
    days_left = (expiry_date.date() - now.date()).days
    return start_date, months, expiry_date, days_left

def latest_record_for_user(query: str):
    payment_records = payment_ws.get_all_records()
    application_records = application_ws.get_all_records()
    all_records = payment_records + application_records
    
    query_norm = query.strip().lower()

    best = None
    best_start = None

    for r in all_records:
        email = (r.get("Email Address") or r.get("Email") or "").strip().lower()
        telegram_name = (r.get("Telegram User Name") or r.get("Telegram Username") or "").strip().lower()

        if (email == query_norm) or (telegram_name == query_norm):
            status = compute_status(r)
            if not status:
                continue
            start_date, _, _, _ = status
            if (best_start is None) or (start_date > best_start):
                best_start = start_date
                best = r

    return best

# ---------- Telegram Handlers ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! 🔎 ใช้คำสั่ง\n"
        "/check <email or Telegram username>\n"
        "membership ကျန်ထားသေးသလား စစ်ပေးနိုင်ပါတယ်။"
    )

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Usage: /check <email or Telegram username>")
            return

        query = " ".join(context.args).strip()
        rec = latest_record_for_user(query)
        if not rec:
            await update.message.reply_text(f"❌ No record found for {query}")
            return

        name = get_name(rec)
        status = compute_status(rec)
        if not status:
            await update.message.reply_text("⚠️ Cannot compute dates for this record.")
            return

        start_date, months, expiry_date, days_left = status
        used_source = "Payment Month" if rec.get("Payment Month") else "Timestamp"
        tier = rec.get("Preferred Membership Tier") or rec.get("Membership Tier") or "-"
        telegram_user = rec.get("Telegram User Name") or rec.get("Telegram Username") or "-"

        text = (
            f"👤 {name}\n"
            f"📧 Email: {rec.get('Email Address') or '-'}\n"
            f"📞 Telegram: {telegram_user}\n"
            f"🏷️ Tier: {tier}\n"
            f"🗓 Start ({used_source}): {start_date.strftime('%Y-%m-%d')}\n"
            f"⏳ Duration: {months} month(s)\n"
            f"🏁 Expire: {expiry_date.strftime('%Y-%m-%d')}\n"
        )

        if days_left > 1:
            text += f"✅ Remaining: {days_left} days"
        elif days_left == 1:
            text += "⚠️ Remaining: 1 day"
        elif days_left == 0:
            text += "⏰ Expiring today!"
        else:
            text += f"❌ Expired {abs(days_left)} day(s) ago"

        await update.message.reply_text(text)

    except Exception as e:
        logging.error(f"Error in check_command: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        payment_records = payment_ws.get_all_records()
        application_records = application_ws.get_all_records()
        all_records = payment_records + application_records

        latest_by_email = {}
        for r in all_records:
            email = (r.get("Email Address") or r.get("Email") or "").strip().lower()
            if not email:
                continue
            status = compute_status(r)
            if not status:
                continue
            start_date, _, _, _ = status
            prev = latest_by_email.get(email)
            if (prev is None) or (start_date > prev[0]):
                latest_by_email[email] = (start_date, r)

        msgs = []
        for email, (_, r) in latest_by_email.items():
            res = compute_status(r)
            if not res:
                continue
            _, _, expiry_date, days_left = res
            if days_left == 1:
                name = get_name(r)
                msgs.append(f"⏰ {name} ({email}) expires tomorrow ({expiry_date.strftime('%Y-%m-%d')})")

        if msgs:
            await context.bot.send_message(chat_id=USER_ID, text="Membership reminders:\n" + "\n".join(msgs))

    except Exception as e:
        logging.error(f"Error in daily_reminder: {e}")

# ---------- Main (Entry Point) ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("check", cmd_check))

    app.job_queue.run_daily(daily_reminder, time=dtime(hour=8, minute=0), name="daily_reminder_morning")
    app.job_queue.run_daily(daily_reminder, time=dtime(hour=12, minute=0), name="daily_reminder_noon")

    # Determine whether to run with polling or webhook
    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        port = int(os.environ.get("PORT", "8000"))
        logging.info(f"Bot starting with webhook. URL={webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{webhook_url}{BOT_TOKEN}",
        )
    else:
        logging.warning("WEBHOOK_URL not set, running with polling...")
        app.run_polling()

if __name__ == "__main__":
    main()

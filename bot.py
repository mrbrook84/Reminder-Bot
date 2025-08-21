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
from telegram.ext import Application, CommandHandler, ContextTypes

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

# Sheet IDs
PAYMENT_SHEET_ID = "1ffDReFiVQfH3Ss2nUEclha3cW8X2h3dglrdFtZX4cjc"
APPLICATION_SHEET_ID = "1WVqOCZeSGwoZuw5bauDn5eaLO51XLcMDhcZPWuKkrxw"

# Sheet Titles
PAYMENT_SHEET_TITLE = "Form Responses 1"
APPLICATION_SHEET_TITLE = "Form_Responses"

# Worksheets
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

def latest_record_for_email(email: str):
    """
    Scan both sheets for this email; pick the one with the latest start_date.
    """
    records = []
    records.extend(payment_ws.get_all_records())
    records.extend(application_ws.get_all_records())

    best = None
    best_start = None
    for r in records:
        e = (r.get("Email Address") or r.get("Email") or "").strip().lower()
        if e != email.strip().lower():
            continue
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
        "/check <email>\n"
        "membership ကျန်ထားသေးသလား စစ်ပေးနိုင်ပါတယ်။"
    )

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Usage: /check <email>")
            return

        email = " ".join(context.args).strip()
        rec = latest_record_for_email(email)
        if not rec:
            await update.message.reply_text(f"❌ No record found for {email}")
            return

        name = get_name(rec)
        status = compute_status(rec)
        if not status:
            await update.message.reply_text("⚠️ Cannot compute dates for this record.")
            return

        start_date, months, expiry_date, days_left = status
        used_source = "Payment Month" if rec.get("Payment Month") else "Timestamp"
        tier = rec.get("Preferred Membership Tier") or rec.get("Membership Tier") or "-"

        text = (
            f"👤 {name}\n"
            f"📧 {email}\n"
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
        records = []
        records.extend(payment_ws.get_all_records())
        records.extend(application_ws.get_all_records())

        latest_by_email = {}
        for r in records:
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

# ---------- Main (Polling) ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("check", cmd_check))

    app.job_queue.run_daily(daily_reminder, time=dtime(hour=0, minute=0), name="daily_reminder")

    logging.info(f"Bot starting (polling). TZ={TZ_NAME}")
    app.run_polling()

if __name__ == "__main__":
    main()

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, time as dtime
from dateutil.relativedelta import relativedelta
import re
import logging
import os
import json

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(os.environ['GOOGLE_CREDENTIALS']), scope)
client = gspread.authorize(creds)

# Sheet names
PAYMENT_SHEET = "Form Responses 1"  # For Monthly Member Fee Payment
APPLICATION_SHEET = "Form Responses 1"  # For Music Membership Application

# Telegram Bot setup
BOT_TOKEN = os.environ['BOT_TOKEN']
USER_ID = os.environ['USER_ID']

# Load sheets with provided Sheet IDs
payment_sheet = client.open_by_key("1ffDReFiVQfH3Ss2nUEclha3cW8X2h3dglrdFtZX4cjc").worksheet(PAYMENT_SHEET)
application_sheet = client.open_by_key("1WVqOCZeSGwoZuw5bauDn5eaLO51XLcMDhcZPWuKkrxw").worksheet(APPLICATION_SHEET)

# Helper functions
def parse_duration(comment):
    if not comment:
        return 1  # Default 1 month
    match = re.search(r'(\d+)\s*month', comment, re.IGNORECASE)
    return int(match.group(1)) if match else 1

def calculate_expiry(payment_date, duration):
    payment_date = datetime.strptime(payment_date, '%m/%d/%Y')
    expiry_date = payment_date + relativedelta(months=duration)
    days_left = (expiry_date - datetime.now()).days
    return expiry_date, days_left

# Telegram commands
async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        email = context.args[0] if context.args else None
        if not email:
            await update.message.reply_text("Usage: /check <email>")
            return

        records = payment_sheet.get_all_records()
        latest_payment = None
        for record in records:
            if record['Email Address'].lower() == email.lower():
                if not latest_payment or datetime.strptime(record['Timestamp'], '%m/%d/%Y') > datetime.strptime(latest_payment['Timestamp'], '%m/%d/%Y'):
                    latest_payment = record

        if not latest_payment:
            await update.message.reply_text(f"No payment record found for {email}")
            return

        member_name = latest_payment['Member Name']
        payment_date = latest_payment['Timestamp']
        comment = latest_payment.get('Any additional comments?', '')
        duration = parse_duration(comment)
        expiry_date, days_left = calculate_expiry(payment_date, duration)

        await update.message.reply_text(f"{member_name} ရဲ့ membership expires in {days_left} days.")
    except Exception as e:
        logging.error(f"Error in check_command: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

# Reminder job
async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    records = payment_sheet.get_all_records()
    for record in records:
        payment_date = record['Timestamp']
        comment = record.get('Any additional comments?', '')
        duration = parse_duration(comment)
        expiry_date, days_left = calculate_expiry(payment_date, duration)
        if days_left == 1:
            member_name = record['Member Name']
            await context.bot.send_message(chat_id=USER_ID, text=f"{member_name} ရဲ့ membership expires in 1 day.")

# Main function (Polling)
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Add command handler
    app.add_handler(CommandHandler("check", check_command))

    # Daily reminder at midnight (UTC timezone by default)
    app.job_queue.run_daily(send_reminder, time=dtime(hour=0, minute=0))

    # Start polling (no need for asyncio.run)
    app.run_polling()

if __name__ == "__main__":
    main()

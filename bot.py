import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dateutil.relativedelta import relativedelta
import re
import telegram
from telegram.ext import Application, CommandHandler
import schedule
import time
import logging
import os
import asyncio

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(eval(os.environ['GOOGLE_CREDENTIALS']), scope)
client = gspread.authorize(creds)

# Sheet names
PAYMENT_SHEET = "Monthly Member Fee Payment (Responses)"
APPLICATION_SHEET = "Music Membership Application (Responses)"

# Telegram Bot setup
BOT_TOKEN = os.environ['BOT_TOKEN']
USER_ID = os.environ['USER_ID']

# Load sheets
payment_sheet = client.open(PAYMENT_SHEET).sheet1
application_sheet = client.open(APPLICATION_SHEET).sheet1

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

async def check_command(update, context):
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

async def send_reminder():
    bot = telegram.Bot(token=BOT_TOKEN)
    records = payment_sheet.get_all_records()
    for record in records:
        payment_date = record['Timestamp']
        comment = record.get('Any additional comments?', '')
        duration = parse_duration(comment)
        expiry_date, days_left = calculate_expiry(payment_date, duration)
        if days_left == 1:
            member_name = record['Member Name']
            await bot.send_message(chat_id=USER_ID, text=f"{member_name} ရဲ့ membership expires in 1 day.")

def run_schedule():
    schedule.every().day.at("00:00").do(lambda: asyncio.run(send_reminder()))
    while True:
        schedule.run_pending()
        time.sleep(60)

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("check", check_command))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    run_schedule()

if __name__ == '__main__':
    asyncio.run(main())
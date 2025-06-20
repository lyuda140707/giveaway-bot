import os
import logging
import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputTextMessageContent, InlineQueryResultArticle
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# === Load env ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# === Google Sheets ===
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDENTIALS = Credentials.from_service_account_info(
    json.loads(os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")), scopes=SCOPES
)
sheet_service = build("sheets", "v4", credentials=CREDENTIALS)
sheet = sheet_service.spreadsheets()

# === Telegram ===
bot = Bot(token=BOT_TOKEN)
Bot.set_current(bot)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# === FastAPI ===
app = FastAPI()

# === Канали ===
CHANNELS = {
    "kino": "@KinoTochkaUA",
    "films": "@KinoTochkaFilms"
}

@app.get("/")
async def root():
    return {"status": "Giveaway bot is running!"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.process_update(update)
        return JSONResponse(content={"ok": True})
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

def get_user_row(user_id, channel):
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range="Giveaway!A2:F").execute()
    values = result.get("values", [])
    for i, row in enumerate(values, start=2):
        if len(row) >= 3 and row[0] == str(user_id) and row[2] == channel:
            return i, row
    return None, None

async def update_user_data(user_id, username, channel, new_ref_id):
    row_num, existing = get_user_row(user_id, channel)
    if existing:
        invited_ids = existing[3].split(",") if existing[3] else []
        if new_ref_id != str(user_id) and new_ref_id not in invited_ids:
            invited_ids.append(new_ref_id)
            count = len(invited_ids)

            sheet.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Giveaway!D{row_num}:E{row_num}",
                valueInputOption="RAW",
                body={"values": [[" ,".join(invited_ids), count]]}
            ).execute()

            notify_check = sheet.values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Giveaway!F{row_num}"
            ).execute().get("values", [])

            already_notified = notify_check and notify_check[0][0].lower() == "так"

            if count >= 3 and not already_notified:
                try:
                    await bot.send_message(user_id, "🎉 Ви запросили 3 друзів — ви у розіграші!")
                except:
                    logging.warning(f"Не вдалося надіслати повідомлення {user_id}")

                sheet.values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"Giveaway!F{row_num}",
                    valueInputOption="RAW",
                    body={"values": [["так"]]}
                ).execute()
    else:
        values = [[str(user_id), username or "", channel, new_ref_id, 1, "ні"]]
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Giveaway!A:F",
            valueInputOption="RAW",
            body={"values": values}
        ).execute()

async def check_subscription(user_id: int, channel: str):
    try:
        chat_member = await bot.get_chat_member(channel, user_id)
        return chat_member.status in ["member", "creator", "administrator"]
    except:
        return False

@dp.message_handler(commands=['start'])
async def handle_start(message: types.Message):
    args = message.get_args()
    referral_info = args if args else None

    if referral_info and "_" in referral_info:
        prefix, ref_id = referral_info.split("_", 1)
        if prefix in CHANNELS:
            channel_username = CHANNELS[prefix]

            if await check_subscription(message.from_user.id, channel_username):
                await update_user_data(ref_id, "", prefix, str(message.from_user.id))
                ref_link = f"https://t.me/{bot.username}?start={prefix}_{message.from_user.id}"
                await message.answer(
                    "✅ Підписку підтверджено! Вас зараховано як друга для розіграшу.",
                    reply_markup=InlineKeyboardMarkup().add(
                        InlineKeyboardButton("🔗 Поділитись розіграшем", switch_inline_query=f"{prefix}_{message.from_user.id}")
                    )
                )
            else:
                await message.answer(
                    f"❗ Спочатку підпишись на канал {channel_username}\n"
                    f"Після цього знову відкрий посилання, щоб участь зарахувалась!"
                )
                return

    else:
        for key, ch in CHANNELS.items():
            channel_url = f"https://t.me/{ch.lstrip('@')}"
            kb = InlineKeyboardMarkup().add(
                InlineKeyboardButton(text=f"📢 Перейти до каналу {ch}", url=channel_url)
            )
            await message.answer(
                f"🎉 Вітаю у розіграші Telegram Premium!\n\n"
                f"Щоб взяти участь, спочатку підпишись на канал {ch}\n"
                f"Потім знову відкрий посилання, щоб зарахувалось!",
                reply_markup=kb
            )

@dp.inline_handler()
async def inline_referral_query(inline_query: types.InlineQuery):
    query = inline_query.query.strip()
    if "_" in query:
        prefix, ref_id = query.split("_", 1)
        if prefix in CHANNELS:
            ch = CHANNELS[prefix]
            link = f"https://t.me/{bot.username}?start={prefix}_{ref_id}"
            input_content = InputTextMessageContent(
                f"🎁 Хочеш отримати Telegram Premium?\n"
                f"Підпишись на {ch} і запроси 3 друзів 👉 {link}"
            )
            result = InlineQueryResultArticle(
                id="1",
                title="Запросити друзів у розіграш",
                description="Отримай Telegram Premium за активність",
                input_message_content=input_content
            )
            await bot.answer_inline_query(inline_query.id, results=[result], cache_time=1)

WEBHOOK_PATH = "/webhook"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.environ.get("PORT", 8000))

async def on_startup(dp):
    logging.info("🚀 Стартуємо Webhook...")
    await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
    logging.info(f"Webhook встановлено: {WEBHOOK_URL + WEBHOOK_PATH}")

async def on_shutdown(dp):
    logging.info("❌ Видаляємо webhook...")
    await bot.delete_webhook()

async def set_webhook_manually():
    webhook_url = WEBHOOK_URL + WEBHOOK_PATH
    success = await bot.set_webhook(webhook_url)
    if success:
        logging.info(f"✅ Webhook manually set: {webhook_url}")
    else:
        logging.error("❌ Failed to set webhook manually")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(set_webhook_manually())
    import uvicorn
    uvicorn.run("bot:app", host=WEBAPP_HOST, port=WEBAPP_PORT)

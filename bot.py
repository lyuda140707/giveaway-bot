import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import uvicorn
import asyncio
from fastapi import FastAPI, Request
from aiogram import types as aio_types
from fastapi.responses import JSONResponse
import json

from aiogram import types
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv


logging.basicConfig(level=logging.INFO)

# === Load env ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Наприклад: https://your-render-url.onrender.com/webhook

# === Google Sheets ===
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
import json
CREDENTIALS = Credentials.from_service_account_info(
    json.loads(os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")), scopes=SCOPES
)

sheet_service = build("sheets", "v4", credentials=CREDENTIALS)
sheet = sheet_service.spreadsheets()

# === Telegram ===
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

app = FastAPI()

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
        update = aio_types.Update(**data)
        await dp.process_update(update)
        return JSONResponse(content={"ok": True})
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
def get_user_row(user_id, channel):
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range="Giveaway!A2:E").execute()
    values = result.get("values", [])
    for i, row in enumerate(values, start=2):
        if len(row) >= 3 and row[0] == str(user_id) and row[2] == channel:
            return i, row
    return None, None

def update_user_data(user_id, username, channel, new_ref_id):
    row_num, existing = get_user_row(user_id, channel)
    if existing:
        invited_ids = existing[3].split(",") if existing[3] else []
        if new_ref_id not in invited_ids:
            invited_ids.append(new_ref_id)
        count = len(invited_ids)
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"Giveaway!D{row_num}:E{row_num}",
            valueInputOption="RAW",
            body={"values": [[",".join(invited_ids), count]]}
        ).execute()
    else:
        values = [[str(user_id), username or "", channel, new_ref_id, 1]]
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Giveaway!A:E",
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
    logging.info(f"▶️ /start отримано від {message.from_user.id} ({message.from_user.username})")
    args = message.get_args()
    referral_info = args if args else None

    if referral_info:
        if "_" in referral_info:
            prefix, ref_id = referral_info.split("_", 1)
            channel_key = prefix if prefix in CHANNELS else None
            if channel_key:
                channel_username = CHANNELS[channel_key]
                if await check_subscription(message.from_user.id, channel_username):
                    update_user_data(ref_id, "", channel_key, str(message.from_user.id))
                    await message.answer("✅ Ви підписались через реферальне посилання. Вашого друга зараховано!")
                else:
                    await message.answer(f"❗ Спочатку підпишіться на {channel_username}, щоб бути зарахованим.")
                return

    kb = InlineKeyboardMarkup(row_width=1)
    for key, ch in CHANNELS.items():
        link = f"https://t.me/GiveawayKinoBot?start={key}_{message.from_user.id}"
        kb.add(InlineKeyboardButton(text=f"Запросити друзів у {ch}", url=link))

    await message.answer(
        "🎉 Вітаю у розіграші Telegram Premium!\n\nПідпишись на канал і запроси 3 друзів, щоб взяти участь.\n\nОбери канал і отримай своє унікальне посилання:",
        reply_markup=kb
    )


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
    import uvicorn
    loop = asyncio.get_event_loop()
    loop.run_until_complete(set_webhook_manually())  # ⬅️ Додано цей виклик
    loop.create_task(on_startup(dp))
    uvicorn.run("bot:app", host=WEBAPP_HOST, port=WEBAPP_PORT)

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
from contextlib import asynccontextmanager

from aiogram import types
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
import urllib.parse
import random

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
Bot.set_current(bot)  # <== обов’язково
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

app = FastAPI()

CHANNELS = {
    "kino": "@KinoTochkaUA",
    "films": "@KinoTochkaFilms",
    "test": "@testbotKana"
}

@app.get("/")
async def root():
    return {"status": "Giveaway bot is running!"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        Bot.set_current(bot)  # <== Додай це тут
        data = await request.json()
        update = types.Update(**data)
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

async def update_user_data(user_id, username, channel, ref_id):
    # 1. Додаємо нового користувача, якщо його ще нема
    user_row_num, user_row = get_user_row(user_id, channel)
    if not user_row:
        logging.info(f"📥 Додаємо нового користувача {user_id} у канал {channel}")
        ref_id_str = str(ref_id) if ref_id else ""
        values = [[str(user_id), username or "", channel, ref_id_str, 0, "ні"]]
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Giveaway!A:F",
            valueInputOption="RAW",
            body={"values": values}
        ).execute()
    

   
        

    # 2. Оновлюємо інформацію про того, хто запросив
    ref_row_num, ref_row = get_user_row(ref_id, channel)
    if ref_row:
        invited_ids = ref_row[3].split(",") if len(ref_row) >= 4 and ref_row[3] else []

        if str(user_id) != str(ref_id) and str(user_id) not in invited_ids:
            invited_ids.append(str(user_id))
            count = len(invited_ids)

            # Оновлюємо invited_ids і count
            sheet.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Giveaway!D{ref_row_num}:E{ref_row_num}",
                valueInputOption="RAW",
                body={"values": [[",".join(invited_ids), count]]}
            ).execute()

            # Перевірка чи вже повідомляли
            notify_check = sheet.values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Giveaway!F{ref_row_num}"
            ).execute().get("values", [])
            already_notified = notify_check and notify_check[0][0].lower() == "так"

            # 📨 Повідомлення про кожного друга
            try:
                await bot.send_message(
                    int(ref_id),
                    f"🎯 Хтось підписався по вашому посиланню!\n🔢 Запрошено: {count} з 3"
                )
            except Exception as e:
                logging.warning(f"⚠️ Не вдалося надіслати повідомлення {ref_id}: {e}")

            # 🎉 Якщо 3 або більше — надсилаємо фінальне
            if count >= 3 and not already_notified:
                try:
                    await bot.send_message(
                        int(ref_id),
                        "🎉 Ви запросили 3 друзів — ви у розіграші!"
                    )
                except Exception as e:
                    logging.warning(f"⚠️ Не вдалося надіслати повідомлення {ref_id}: {e}")

                sheet.values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"Giveaway!F{ref_row_num}",
                    valueInputOption="RAW",
                    body={"values": [["так"]]}
                ).execute()



async def check_subscription(user_id: int, channel: str):
    try:
        chat_member = await bot.get_chat_member(channel, user_id)
        logging.info(f"👁 Перевірка підписки: {user_id} у {channel} — статус: {chat_member.status}")
        return chat_member.status in ("member", "administrator", "creator")
    except Exception as e:
        logging.error(f"❌ Помилка при перевірці підписки {user_id} у {channel}: {e}")
        return False


    
@dp.message_handler(commands=['start'])
async def handle_start(message: types.Message):
    logging.info(f"▶️ /start отримано від {message.from_user.id} ({message.from_user.username})")
    user_id = message.from_user.id
    username = message.from_user.username
    args = message.get_args()
    referral_info = args if args else None

    if referral_info and "_" in referral_info:
        prefix, ref_id = referral_info.split("_", 1)
        channel_key = prefix if prefix in CHANNELS else None

        if channel_key:
            channel_username = CHANNELS[channel_key]
            ref_row_num, _ = get_user_row(ref_id, channel_key)
            # 👇 не додаємо ref_id, якщо він дорівнює user_id
            if str(ref_id) != str(user_id):
                # 👇 Додаємо реферала лише якщо він уже є в таблиці (тобто ref_row_num існує)
                if str(ref_id) != str(user_id):
                    if ref_row_num:
                        logging.info(f"✔️ ref_id {ref_id} вже є у таблиці — все добре")
                    else:
                        logging.info(f"➕ ref_id {ref_id} ще не у таблиці — додаємо як реферала")
                        await update_user_data(ref_id, None, channel_key, None)
            
            
            
            share_text = (
                f"🎁 Розіграш Telegram Premium!\n\n"
                f"💬 Натисни 👇 це посилання:\n"
                f"https://t.me/GiveawayKinoBot?start={channel_key}_{user_id}\n\n"
                f"🟢 Бот усе пояснить:\n"
                f"1️⃣ Підписка на канал\n"
                f"2️⃣ Запрошення друзів\n"
                f"3️⃣ Участь у розіграші!"
               
            )
            ref_link = f"https://t.me/GiveawayKinoBot?start={channel_key}_{user_id}"
            share_link = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote(share_text)}"
            


            kb = InlineKeyboardMarkup().add(
                InlineKeyboardButton(text="Поділитися посиланням", url=share_link)
            ).add(
                InlineKeyboardButton("✅ Я підписався", callback_data=f"check_{channel_key}_{ref_id}")
            )

            await message.answer(
                f"🔔 Перш ніж брати участь, підпишись на канал {channel_username} і повернись сюди.\n"
                f"Після підписки натисни кнопку нижче 👇",
                reply_markup=kb
            )
            return  # 🛑 Зупиняємо, бо вже показали кнопки

    # 🔻 Якщо користувач зайшов без рефералки — випадково обираємо канал
    channel_key = random.choice(list(CHANNELS.keys()))
    channel_username = CHANNELS[channel_key]

    ref_link = f"https://t.me/GiveawayKinoBot?start={channel_key}_{user_id}"
    share_text = (
        f"🎁 Участь у розіграші Telegram Premium!\n\n"
        f"🔗 Тисни тут:\n"
        f"{ref_link}\n\n"
        f"📌 Підпишись на {channel_username} — і запроси друзів!"
    )
    share_link = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote(share_text)}"

    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton(text=f"Поділитися через {channel_username}", url=share_link)
    )

    await message.answer(
        "🎉 Вітаю у розіграші Telegram Premium!\n\n"
        "Підпишись на канал і запроси **мінімум 3 друзів**.\n"
        "⚠️ Щойно всі вони теж підпишуться — ти автоматично потрапиш у список учасників!\n\n"
        "👇 Отримай своє унікальне посилання:",
        reply_markup=keyboard
    )





@dp.callback_query_handler(lambda c: c.data.startswith("check_"))
async def process_check_subscription(callback_query: types.CallbackQuery):
    await callback_query.answer()
    _, channel_key, ref_id = callback_query.data.split("_", 2)
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username
    channel_username = CHANNELS[channel_key]

    # Захист від повторного проходження
    user_row_num, _ = get_user_row(user_id, channel_key)
    if await check_subscription(user_id, channel_username):
        if not user_row_num:
            # Користувача ще нема — додаємо і реферал, якщо не self-ref
            await update_user_data(user_id, username, channel_key, str(ref_id))
        else:
            # Користувач уже є — додаємо без ref_id (щоб не затирати)
            await update_user_data(user_id, username, channel_key, None)

        ref_link = f"https://t.me/GiveawayKinoBot?start={channel_key}_{user_id}"
        share_text = (
            f"🎁 Telegram Premium чекає на тебе!\n"
            f"👉 Натисни: https://t.me/GiveawayKinoBot?start={channel_key}_{user_id}\n"
            f"🎬 Підпишись і запрошуй друзів!"
        )
        share_link = f"https://t.me/share/url?url={ref_link}&text={share_text}"

        kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton(text="Поділитися посиланням", url=share_link)
        )
        await callback_query.message.answer(
            "🎉 Ви успішно приєдналися!\n\n"
            "📩 Тепер поділись своїм посиланням із друзями.\n"
            "Коли **3 з них підпишуться** — ти автоматично береш участь у розіграші!",
            reply_markup=kb
        )
    else:
        logging.info(f"❌ {user_id} ще не підписався на {channel_username}")
        await callback_query.answer("❗ Ви ще не підписались!", show_alert=True)





WEBHOOK_PATH = "/webhook"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.environ.get("PORT", 8000))

async def on_startup(dp):
    Bot.set_current(bot)  # <== сюди теж
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
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

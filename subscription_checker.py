import os
import asyncio
from aiogram import Bot
from google_api import get_google_service

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
CHANNEL_USERNAME = "@KinoTochkaFilms"  # твій канал

bot = Bot(token=BOT_TOKEN)

async def check_all_users():
    print("🔁 Перевіряємо підписку всіх користувачів...")
    service = get_google_service()
    sheet = service.spreadsheets()

    users = sheet.values().get(
        spreadsheetId=SHEET_ID,
        range="Лист1!A2:A"  # діапазон user_id
    ).execute().get("values", [])

    for i, row in enumerate(users):
        if not row:
            continue

        user_id = int(row[0])
        try:
            member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
            status = member.status
            print(f"👤 {user_id} — {status}")

            if status in ["member", "administrator", "creator"]:
                status_text = "✅ Підписаний"
            else:
                status_text = "❌ Вийшов"

            # запис у стовпець B
            sheet.values().update(
                spreadsheetId=SHEET_ID,
                range=f"Лист1!B{i+2}",
                valueInputOption="RAW",
                body={"values": [[status_text]]}
            ).execute()

        except Exception as e:
            print(f"⚠️ Помилка перевірки {user_id}: {e}")

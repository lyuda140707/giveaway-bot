import time
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    while True:
        logging.info("👀 Worker is alive! Checking background task...")
        # Наприклад, оновлення Google Таблиці, або ще щось
        time.sleep(300)  # кожні 5 хвилин

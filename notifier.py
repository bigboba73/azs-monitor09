import os
import requests


def send_telegram_alert(text: str) -> bool:
    """Отправляет текстовое уведомление в Telegram через Bot API."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print(
            "Ошибка: переменные TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы."
        )
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("Оповещение успешно отправлено в Telegram.")
        return True
    except requests.RequestException as e:
        print(f"Не удалось отправить сообщение в Telegram: {e}")
        return False

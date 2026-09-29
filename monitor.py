from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
from urllib.parse import urljoin

import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
STATE_FILE = BASE_DIR / "state.json"

MSK = timezone(timedelta(hours=3))


def now_msk():
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M")


def fetch_station():
    url = urljoin(
        CONFIG["base_url"] + "/", f"api/stations/{CONFIG['station_id']}"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "Referer": CONFIG["base_url"] + "/fuel/refuel-map",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def fuel_status(item):
    rest = item.get("rest") or {}
    avail = bool(rest.get("avail"))
    delivery = rest.get("delivery")
    if avail:
        return "В НАЛИЧИИ"
    if delivery != "no":
        return "В ПУТИ"
    return "НЕТ В НАЛИЧИИ"


def fetch_statuses():
    out = {}
    for item in fetch_station():
        product = item.get("product") or {}
        title = product.get("title") or product.get("shortTitle") or "?"
        out[title] = fuel_status(item)
    return out


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state):
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    if STATE_FILE.exists() and STATE_FILE.read_text(encoding="utf-8") == payload:
        return
    STATE_FILE.write_text(payload, encoding="utf-8")


def send_telegram(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise ValueError(
            "Не заданы переменные окружения TELEGRAM_BOT_TOKEN или"
            " TELEGRAM_CHAT_ID"
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=20)
    resp.raise_for_status()


def build_message(statuses, changes, fetched_at):
    lines = [
        f"⛽ <b>АЗС {CONFIG['station_id']}: {CONFIG['station_name']}</b>",
        f"🕒 Время проверки: <i>{fetched_at} МСК</i>",
        "",
        "🔔 <b>Изменилось:</b>",
    ]
    for title in changes:
        lines.append(f"  • <b>{title}</b>: <u>{statuses[title]}</u>")

    lines.append("")
    lines.append("📋 <b>Все виды топлива:</b>")
    for title, status in statuses.items():
        lines.append(f"  • {title}: {status}")

    return "\n".join(lines)


def build_welcome_message(statuses, fetched_at):
    lines = [
        "🚀 <b>Мониторинг АЗС успешно запущен!</b>",
        f"⛽ <b>АЗС {CONFIG['station_id']}: {CONFIG['station_name']}</b>",
        f"🕒 Время первого запуска: <i>{fetched_at} МСК</i>",
        "",
        "📋 <b>Текущие статусы топлива:</b>",
    ]
    for title, status in statuses.items():
        lines.append(f"  • {title}: {status}")

    lines.append("")
    lines.append(
        "<i>Следующие уведомления будут приходить только при изменениях.</i>"
    )
    return "\n".join(lines)


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    try:
        statuses = fetch_statuses()
    except Exception as exc:
        logging.error("Не удалось получить данные: %s", exc)
        return 0

    state = load_state()
    fetched_at = now_msk()

    # 1. Самый первый запуск (state.json не существовал или был пуст)
    if not state:
        logging.info("Первый запуск: отправка приветствия и сохранение базы.")
        welcome_body = build_welcome_message(statuses, fetched_at)
        try:
            send_telegram(welcome_body)
            logging.info("Приветственное сообщение успешно отправлено.")
        except Exception as exc:
            logging.error("Ошибка отправки приветствия в Telegram: %s", exc)
            return 1

        state.update(statuses)
        save_state(state)
        return 0

    # 2. Повторные запуски — ищем расхождения со сохранённым состоянием
    changes = [
        title for title, status in statuses.items() if state.get(title) != status
    ]

    if not changes:
        logging.info("Изменений нет: %s", statuses)
        state.update(statuses)
        save_state(state)
        return 0

    # 3. Отправка отчёта об изменениях
    body = build_message(statuses, changes, fetched_at)
    try:
        send_telegram(body)
        logging.info("Оповещение об изменениях успешно отправлено в Telegram.")
    except Exception as exc:
        logging.error("Ошибка отправки в Telegram: %s", exc)
        return 1

    state.update(statuses)
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

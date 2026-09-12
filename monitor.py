import json
import logging
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
STATE_FILE = BASE_DIR / "state.json"
RECIPIENTS_FILE = BASE_DIR / "recipients.txt"

MSK = timezone(timedelta(hours=3))


def now_msk():
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M")


def load_recipients():
    raw = RECIPIENTS_FILE.read_text(encoding="utf-8")
    return [line.strip() for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")]


def fetch_station():
    url = urljoin(CONFIG["base_url"] + "/", f"api/stations/{CONFIG['station_id']}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
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
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    if STATE_FILE.exists() and STATE_FILE.read_text(encoding="utf-8") == payload:
        return
    STATE_FILE.write_text(payload, encoding="utf-8")


def send_email(subject, body, recipients):
    sender = CONFIG["sender"]
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("Монитор АЗС Газпромнефть", "utf-8")), sender))
    msg["To"] = ", ".join(recipients)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx, timeout=30) as server:
        server.login(user, password)
        server.sendmail(sender, recipients, msg.as_string())


def build_message(statuses, changes, fetched_at):
    lines = [
        f"АЗС: {CONFIG['station_name']}",
        f"Время проверки: {fetched_at} МСК",
        "",
        "Изменилось:",
    ]
    for title in changes:
        lines.append(f"  • {title}: {statuses[title]}")
    lines.append("")
    lines.append("Все виды топлива:")
    for title, status in statuses.items():
        lines.append(f"  • {title}: {status}")
    lines.append("")
    lines.append("Это автоматическое сообщение от мониторинга gpnbonus.ru.")
    return "\n".join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        statuses = fetch_statuses()
    except Exception as exc:
        logging.error("Не удалось получить данные: %s", exc)
        return 0

    state = load_state()
    changes = [title for title, status in statuses.items() if state.get(title) != status]
    fetched_at = now_msk()

    if not changes:
        logging.info("Изменений нет: %s", statuses)
        state.update(statuses)
        save_state(state)
        return 0

    recipients = load_recipients()
    if not recipients:
        logging.error("recipients.txt пуст — письмо не отправлено, статус: %s", statuses)
        return 1

    changed_text = "; ".join(f"{title} — {status}" for title, status in statuses.items() if title in changes)
    subject = f"АЗС {CONFIG['station_id']}: {changed_text} ({fetched_at})"
    body = build_message(statuses, changes, fetched_at)

    try:
        send_email(subject, body, recipients)
        logging.info("Отправлено письмо: %s", subject)
    except Exception as exc:
        logging.error("Ошибка отправки почты: %s", exc)
        return 1

    state.update(statuses)
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
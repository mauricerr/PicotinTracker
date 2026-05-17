from __future__ import annotations

import mimetypes
import os
import smtplib
import ssl
import uuid
from abc import ABC, abstractmethod
from email.message import EmailMessage
from pathlib import Path
from urllib import request

from .models import InventoryHit


class Notifier(ABC):
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def send(self, hit: InventoryHit) -> None:
        raise NotImplementedError


def hit_message(hit: InventoryHit) -> str:
    return "\n".join(
        (
            "Picotin inventory confirmed",
            f"Product: {hit.product_name}",
            f"Color: {hit.color}",
            f"Size: {hit.size}",
            f"Price: {hit.price}",
            f"URL: {hit.url}",
            f"Timestamp: {hit.timestamp}",
        )
    )


def _post_multipart(url: str, fields: dict[str, str], files: dict[str, Path]) -> None:
    boundary = f"----picotin-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    for name, path in files.items():
        if not path.exists():
            continue
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{path.name}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    body = b"".join(chunks)
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"notification failed with HTTP {response.status}")


def _post_json(url: str, payload: str) -> None:
    req = request.Request(
        url,
        data=payload.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"notification failed with HTTP {response.status}")


class TelegramNotifier(Notifier):
    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, hit: InventoryHit) -> None:
        base = f"https://api.telegram.org/bot{self.token}"
        if hit.screenshot_path and hit.screenshot_path.exists():
            _post_multipart(
                f"{base}/sendPhoto",
                {"chat_id": self.chat_id, "caption": hit_message(hit)},
                {"photo": hit.screenshot_path},
            )
            return
        _post_multipart(f"{base}/sendMessage", {"chat_id": self.chat_id, "text": hit_message(hit)}, {})


class DiscordNotifier(Notifier):
    def __init__(self) -> None:
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")

    def configured(self) -> bool:
        return bool(self.webhook_url)

    def send(self, hit: InventoryHit) -> None:
        payload = (
            '{"content": '
            + _json_string(hit_message(hit))
            + ', "allowed_mentions": {"parse": []}}'
        )
        if hit.screenshot_path and hit.screenshot_path.exists():
            _post_multipart(self.webhook_url, {"payload_json": payload}, {"files[0]": hit.screenshot_path})
            return
        _post_json(self.webhook_url, payload)


class PushoverNotifier(Notifier):
    def __init__(self) -> None:
        self.app_token = os.getenv("PUSHOVER_APP_TOKEN", "")
        self.user_key = os.getenv("PUSHOVER_USER_KEY", "")

    def configured(self) -> bool:
        return bool(self.app_token and self.user_key)

    def send(self, hit: InventoryHit) -> None:
        fields = {
            "token": self.app_token,
            "user": self.user_key,
            "title": "Picotin inventory confirmed",
            "message": hit_message(hit),
            "url": hit.url,
        }
        files = {"attachment": hit.screenshot_path} if hit.screenshot_path else {}
        _post_multipart("https://api.pushover.net/1/messages.json", fields, files)


class EmailNotifier(Notifier):
    def __init__(self) -> None:
        self.host = os.getenv("SMTP_HOST", "")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.username = os.getenv("SMTP_USERNAME", "")
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.sender = os.getenv("SMTP_FROM", self.username)
        self.recipient = os.getenv("SMTP_TO", "")
        self.use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}

    def configured(self) -> bool:
        return bool(self.host and self.sender and self.recipient)

    def send(self, hit: InventoryHit) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"{hit.product_name} {hit.color} confirmed"
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.set_content(hit_message(hit))
        if hit.screenshot_path and hit.screenshot_path.exists():
            maintype, subtype = (mimetypes.guess_type(hit.screenshot_path.name)[0] or "image/png").split("/", 1)
            msg.add_attachment(
                hit.screenshot_path.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                filename=hit.screenshot_path.name,
            )
        with smtplib.SMTP(self.host, self.port, timeout=30) as server:
            if self.use_tls:
                server.starttls(context=ssl.create_default_context())
            if self.username:
                server.login(self.username, self.password)
            server.send_message(msg)


def _json_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def choose_notifier() -> Notifier | None:
    for notifier in (TelegramNotifier(), DiscordNotifier(), PushoverNotifier(), EmailNotifier()):
        if notifier.configured():
            return notifier
    return None

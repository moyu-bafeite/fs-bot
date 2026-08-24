"""Telegram Bot API 推送客户端。"""

from __future__ import annotations

import asyncio
import os

from telegram import Bot
from telegramify_markdown import markdownify


class TelegramNotifier:
    """Telegram 频道/群组消息推送器。

    用法::

        notifier = TelegramNotifier()  # 从环境变量读取 token/chat_id
        notifier.send("# Hello\nSome **bold** text")

        # 或显式传入
        notifier = TelegramNotifier(token="xxx", chat_id="-100xxx")
    """

    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        if not self._token or not self._chat_id:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID 未配置"
            )
        self._bot = Bot(token=self._token)

    def send(self, text: str, markdown: bool = True) -> None:
        """发送消息。

        Args:
            text: 消息内容（标准 Markdown 格式）。
            markdown: 是否转换为 Telegram MarkdownV2 格式。False 则纯文本发送。
        """
        if markdown:
            text = markdownify(text)
        asyncio.run(self._send_all(text, markdown))

    async def _send_all(self, text: str, markdown: bool) -> None:
        """异步发送，超长自动拆分。"""
        chunks = self._split(text)
        for chunk in chunks:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=chunk,
                parse_mode="MarkdownV2" if markdown else None,
                disable_web_page_preview=True,
            )

    @staticmethod
    def _split(text: str) -> list[str]:
        """按长度拆分消息（Telegram 限制 4096 字符）。"""
        if len(text) <= 4096:
            return [text]

        chunks: list[str] = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > 4090:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)
        return chunks

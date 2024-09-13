from os import getenv

from aiogram import Bot
from telethon import TelegramClient, events

from ai_wrapper import AiWrapper


class TelethonBot:
    def __init__(self, bot: Bot, postgres_wrapper):
        api_id = getenv("TELEGRAM_API_ID")
        api_hash = getenv("TELEGRAM_API_HASH")
        self.client = TelegramClient(
            session="CheckAnalysis", api_id=int(api_id), api_hash=api_hash
        )
        self.bot = bot
        self.postgres_wrapper = postgres_wrapper
        self.ai_wrapper = AiWrapper()

    async def start(self):
        async with self.client:
            me = await self.client.get_me()
            print(me.username)

            self.target_chat = await self.client.get_entity("@Cheki_FNS_bot")
            # self.send_chat = await self.client.get_entity("@wheremymoney_bot")

            self.client.add_event_handler(self.handle_new_message, events.NewMessage)

            await self.client.run_until_disconnected()

    async def handle_new_message(self, event):
        me = await self.client.get_me()
        sender = await event.message.get_sender()
        if event.chat_id == self.target_chat.id and sender.id == self.target_chat.id:
            message_text = event.message.message
            response = await self.ai_wrapper.validity_check_message(message_text)
            if not response['is_check']:
                return

            spreadsheet = self.postgres_wrapper.spreadsheets_wrapper.get_spreadsheet(me.id)
            self.postgres_wrapper.checks_queue_wrapper.create_check(spreadsheet_id=spreadsheet.id, check_text=message_text)
            await self.bot.send_message(chat_id=me.id, text="Чек добавлен")
            # await self.client.send_message(entity=self.send_chat, message=message_text)

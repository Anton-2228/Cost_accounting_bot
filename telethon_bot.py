from os import getenv

import init

from telethon import TelegramClient, events

class TelethonBot:
    def __init__(self):
        api_id = getenv("TELEGRAM_API_ID")
        api_hash = getenv("TELEGRAM_API_HASH")
        # self.target_chat = "@Cheki_FNS_bot"
        self.client = TelegramClient(session="CheckAnalysis", api_id=int(api_id), api_hash=api_hash)

    async def start(self):
        async with self.client:
            me = await self.client.get_me()
            print(me.username)

            self.target_chat = await self.client.get_entity("@Cheki_FNS_bot")

            self.client.add_event_handler(self.handle_new_message, events.NewMessage)

            await self.client.run_until_disconnected()

    async def handle_new_message(self, event):
        sender = await event.message.get_sender()
        if event.chat_id == self.target_chat.id and sender.id == self.target_chat.id:
            message_text = event.message.message
            print(message_text)

from pyrogram.handlers import MessageHandler
from pyrogram.types import BotCommand, Message as TM, CallbackQuery as TC, User as TU
from loguru import logger

from ..base import MenuBot
from .tree import Tree
from .start import Start
from .on_message import OnMessage
from .admin import Admin


class _Methods(
    Tree,
    OnMessage,
    Start,
    Admin,
):
    pass


class FatherBot(MenuBot, _Methods):
    name = "father"

    async def setup(self):
        self.bot.add_handler(MessageHandler(self.on_messagge))
        self.menu.setup(self.bot)
        await self.bot.set_bot_commands([BotCommand("start", "打开面板")])
        logger.info(f"Now listening updates in: @{self.bot.me.username}.")

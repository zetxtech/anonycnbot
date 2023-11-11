from datetime import datetime, time
from pyrogram import filters, Client
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message as TM, BotCommand
from loguru import logger
from peewee import DoesNotExist

from ..utils import parse_timedelta
from ..model import UserRole, User, PMBan, PMLog
from .base import Bot
from .control import ControlBot

logger = logger.bind(scheme="pm")


class PMBot(Bot):
    name = "embykeeper_pm_bot"

    async def setup(self):
        await self.bot.set_bot_commands(
            [
                BotCommand("start", "开始对话"),
                BotCommand("delete", "删除回复的匿名信息"),
                BotCommand("ban", "(管理员) 禁言 [时长]"),
                BotCommand("unban", "(管理员) 解除禁言"),
            ]
        )
        self.creator = User.get(role=UserRole.CREATOR)
        self.last_guest = self.creator.uid
        self.bot.add_handler(MessageHandler(self.start, filters.command("start")))
        self.bot.add_handler(MessageHandler(self.ban, filters.command("ban")))
        self.bot.add_handler(MessageHandler(self.unban, filters.command("unban")))
        self.bot.add_handler(MessageHandler(self.redirect_host, filters.user(self.creator.uid) & (~filters.service)))
        self.bot.add_handler(MessageHandler(self.redirect_guest, ~filters.service))
        logger.info(f"已启动监听: {self.bot.me.username}.")

    async def start(self, client: Client, message: TM):
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role > UserRole.MEMBER:
            return await client.send_message(sender.id, "👑 尊敬的高级用户, 欢迎使用 Embykeeper PMBot! 有什么可以帮您?")
        else:
            return await client.send_message(
                sender.id,
                "ℹ️ 抱歉, 非高级用户暂不能使用 PMBot, 请通过 [交流群](https://t.me/embykeeperchat) 获得帮助.",
            )

    async def ban(self, client: Client, message: TM):
        rm = message.reply_to_message
        if not rm:
            return await message.reply("⚠️ 您需要回复目标用户的消息.")
        log = PMLog.get_or_none(redirected_message=rm.id)
        if not log:
            return await message.reply("⚠️ 您需要回复目标用户的消息.")
        ur = log.user
        cmd = message.text.split(None, 1)
        try:
            _, duration = cmd
        except ValueError:
            duration = "365 d"
        try:
            td = parse_timedelta(duration)
        except AssertionError:
            return await message.reply("⚠️ 无效时长, 参考: 2d 8h 10m")
        ban = PMBan.get_or_none(user=ur)
        if ban:
            ban.until += td
            ban.save()
        else:
            PMBan(user=ur, until=datetime.now() + td).save()
        return await message.reply("✅ 成功")

    async def unban(self, client: Client, message: TM):
        rm = message.reply_to_message
        if not rm:
            return await message.reply("⚠️ 您需要回复目标用户的消息.")
        log = PMLog.get_or_none(redirected_message=rm.id)
        if not log:
            return await message.reply("⚠️ 您需要回复目标用户的消息.")
        ur = log.user
        ban = PMBan.get_or_none(user=ur)
        if not ban:
            return await message.reply("⚠️ 用户未被封禁")
        ban.delete_instance()
        return await message.reply("✅ 成功")

    async def redirect_host(self, client: Client, message: TM):
        rm = message.reply_to_message
        if not rm:
            await message.copy(self.last_guest)
        else:
            log = PMLog.get_or_none(redirected_message=rm.id)
            if log:
                await message.copy(log.user.uid, reply_to_message_id=log.message)
            else:
                await message.reply("⚠️ 您需要回复对方的消息.")

    async def redirect_guest(self, client: Client, message: TM):
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        ban = PMBan.get_or_none(user=ur)
        if ban:
            return await client.send_message(sender.id, "⚠️ 抱歉, 目前对方正忙.")
        else:
            rmsg = await message.forward(self.creator.uid)
        today_0am = datetime.combine(datetime.today(), time(0, 0))
        try:
            PMLog.get(PMLog.user == ur, PMLog.time > today_0am)
        except DoesNotExist:
            return await message.reply("✅ 已转发给开发者, 请耐心等待回复, 谢谢.")
        else:
            return
        finally:
            PMLog(user=ur, message=message.id, redirected_message=rmsg.id).save()

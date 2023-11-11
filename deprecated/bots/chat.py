import asyncio
from datetime import datetime, timedelta
from enum import Enum, auto
import random
import re
import string

import emoji
from pyrogram import filters, Client
from pyrogram.handlers import MessageHandler, CallbackQueryHandler, EditedMessageHandler
from pyrogram.enums import ChatType
from pyrogram.types import (
    Message as TM,
    User as TU,
    CallbackQuery as TC,
    BotCommand,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import BadRequest, RPCError
from loguru import logger

from ..utils import async_partial, parse_timedelta, truncate_str
from ..model import ChatBan, ChatCustom, db, User, ChatLog, ChatRedirect, UserRole
from .base import Bot
from .control import ControlBot

logger = logger.bind(scheme="chat")


class ConversationStatus(Enum):
    WAITING_EMOJI = auto()


class RoleNotAvailable(Exception):
    pass


class UniqueRole:
    emojis = emoji.distinct_emoji_list("🐶🐱🐹🐰🦊🐼🐯🐮🦁🐸🐵🐔🐧🐥🦆🦅🦉🦄🐝🦋🐌🐙🦖🦀🐠🐳🐘🐿👻🎃🦕🐡🎄🍄🍁🐚🧸🎩🕶🐟🐬🦁🐲🪽🚤🛶")

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.lock = asyncio.Lock()
        self.users = {}
        self.roles = {}

    async def has_role(self, user: User):
        async with self.lock:
            return user.id in self.users

    async def role_for(self, user: User):
        async with self.lock:
            if user.id in self.users:
                return self.users[user.id]
            else:
                return None

    async def get_role(self, user: User, renew=False):
        async with self.lock:
            if user.id in self.users:
                if renew:
                    old_role = self.users[user.id]
                    role = self._get_role()
                    self.users[user.id] = role
                    del self.roles[old_role]
                    self.roles[role] = (user.id, datetime.now())
                    return True, role
                else:
                    role = self.users[user.id]
                    self.roles[role] = (user.id, datetime.now())
                    return False, role
            else:
                role = self._get_role()
                self.users[user.id] = role
                self.roles[role] = (user.id, datetime.now())
                return True, role

    def _get_role(self):
        unused = [e for e in self.emojis if e not in self.roles.keys()]
        if unused:
            return random.choice(unused)
        oldest_avail = None
        for role, (uid, t) in self.roles.items():
            if t > (datetime.now() + timedelta(days=3)):
                continue
            if t < oldest_avail:
                oldest_avail = role
        if oldest_avail:
            uid, _ = self.roles[oldest_avail]
            del self.users[uid]
            return oldest_avail
        else:
            raise RoleNotAvailable()


class ChatBot(Bot):
    name = "embykeeper_chat_bot"

    def __init__(self, *args, welcome_msg: str = None, chat_msg: str = None, **kw):
        super().__init__(*args, **kw)

        self.lock_last_user = asyncio.Lock()
        self.last_user: int = None
        self.welcome_msg: str = welcome_msg.strip() if welcome_msg else ""
        self.chat_msg: str = chat_msg.strip() if chat_msg else ""
        self.unique_roles = UniqueRole()
        self.verifications = {}
        self.callbacks = {}
        self.edit_ids = []
        self.conversations = {}

    async def setup(self):
        await self.bot.set_bot_commands(
            [
                BotCommand("start", "加入群组/显示当前群组信息"),
                BotCommand("delete", "删除回复的匿名信息"),
                BotCommand("change", "随机更改匿名面具"),
                BotCommand("setmask", "(高级用户) 设置匿名面具"),
                BotCommand("restrict", "(管理员) 禁言 [用户] [时长]"),
                BotCommand("unrestrict", "(管理员) 解除禁言 [用户]"),
                BotCommand("ban", "(管理员) 封禁 [用户]"),
                BotCommand("pin", "(管理员) 置顶"),
                BotCommand("unpin", "(管理员) 停止置顶"),
                BotCommand("reveal", "(管理员) 揭示"),
            ]
        )
        self.bot.add_handler(CallbackQueryHandler(self.callback))
        self.bot.add_handler(MessageHandler(self.start, filters.command("start")))
        self.bot.add_handler(MessageHandler(self.delete, filters.private & filters.command("delete")))
        self.bot.add_handler(MessageHandler(self.change, filters.private & filters.command("change")))
        self.bot.add_handler(MessageHandler(self.setmask, filters.private & filters.command("setmask")))
        self.bot.add_handler(MessageHandler(self.restrict, filters.private & filters.command("restrict")))
        self.bot.add_handler(MessageHandler(self.unrestrict, filters.private & filters.command("unrestrict")))
        self.bot.add_handler(MessageHandler(self.ban, filters.private & filters.command("ban")))
        self.bot.add_handler(MessageHandler(self.pin, filters.private & filters.command("pin")))
        self.bot.add_handler(MessageHandler(self.unpin, filters.private & filters.command("unpin")))
        self.bot.add_handler(MessageHandler(self.reveal, filters.private & filters.command("reveal")))
        self.bot.add_handler(MessageHandler(self.process_message, filters.private & (~filters.service)))
        self.bot.add_handler(EditedMessageHandler(self.edit_broadcasted_message, filters.private & (~filters.service)))
        logger.info(f"已启动监听: {self.bot.me.username}.")

    async def change(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        _, role = await self.unique_roles.get_role(ur, renew=True)
        logger.trace(f"[gray50]用户更换了面具 ({sender.name}, {sender.id}): {role}.[/]")
        return await info(f"🌈 您已更换身份, 当前身份是: {role}")

    async def callback(self, client: Client, callback: TC):
        data = self.callbacks[callback.data]
        if data["type"] == "verification":
            uid, event = self.verifications.pop(data["key"])
            event.set()
            return await callback.answer("⭐ 欢迎您, 您的消息已发送")

    async def reveal(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.ADMIN:
            return await info("⚠️ 无权限进行身份揭示.")
        rm = message.reply_to_message
        if not rm:
            return await info("⚠️ 您需要回复需揭示的消息.")
        if rm.from_user.id == self.bot.me.id:
            cr = ChatRedirect.get_or_none(message=rm.id)
            if not cr:
                return await info("⚠️ 消息必须来自其他人.")
            rur = cr.chat.user
        else:
            return await info("⚠️ 消息必须来自其他人.")
        msg_count = ChatLog.select().join(User).where(User.id == rur.id).count()
        try:
            u = await self.bot.get_users(rur.uid)
            un = f"[{u.name}](tg://user?id={rur.uid})"
            if not un:
                un = f"[<已注销>](tg://user?id={rur.uid})"
        except BadRequest:
            un = "<未知>"
        logger.info(f"管理员进行了揭示 ({sender.name}, {sender.id}): {un}, {rur.uid}.")
        return await info(
            "\n".join(
                [
                    f"用户名称: {un}",
                    f"用户 ID: `{rur.uid}`",
                    f"等级状态: {rur.role.name}",
                    f"发言条数: {msg_count}",
                    f"注册时间: {rur.created.strftime('%Y-%m-%d')}",
                ]
            ),
            time=30,
        )

    def set_callback(self, data):
        key = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        self.callbacks[key] = data
        return key

    async def start(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if message.chat.type == ChatType.PRIVATE:
            cmd = message.text.split(None, 1)
            try:
                _, sub = cmd
            except ValueError:
                sub = None
            has_msg = bool(ChatLog.get_or_none(user=ur))
            if (not has_msg) or sub == "new":
                ChatLog(user=ur, message=message.id).save()
                await self.bot.send_message(
                    sender.id,
                    self.welcome_msg.format(user=sender.name),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "Github",
                                    url="https://github.com/embykeeper/embykeeper",
                                ),
                                InlineKeyboardButton("机器人", url="https://t.me/embykeeper_bot"),
                            ]
                        ]
                    ),
                    disable_web_page_preview=True,
                )
                await asyncio.sleep(5)
                await self.bot.send_message(sender.id, "ℹ️ 以下是群内最近十条消息:")
                count = 0
                msgs = []
                for c in ChatLog.select().order_by(ChatLog.time.desc()):
                    try:
                        m = await self.bot.get_messages(c.user.uid, c.message)
                        if not m.text:
                            continue
                        msgs.append(m)
                    except RPCError:
                        continue
                    count += 1
                    if count >= 10:
                        break
                for m in reversed(msgs):
                    await m.copy(sender.id)
                    await asyncio.sleep(random.randint(1, 3))
            else:
                user_count = User.select().join(ChatLog).group_by(User).count()
                chat_count = ChatLog.select().count()
                await info(f"👑 欢迎加入 Embykeeper 交流群\nℹ️ 您发送的消息将匿名转发给本 Bot 的所有用户\n\n⭐ 当前群组信息:\n\n👤 人数: {user_count}\n💬 消息数: {chat_count}")
        else:
            return await info(f"⚠️ 仅可在私聊中联系机器人.")

    async def pin(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.ADMIN:
            return await info("⚠️ 无权限进行置顶.")
        rm = message.reply_to_message
        if not rm:
            return await info("⚠️ 您需要回复需揭示的消息.")
        if not rm.from_user.id == sender.id:
            return await info("⚠️ 只能置顶您的消息.")
        c = ChatLog.get_or_none(message=rm.id)
        if not c:
            return await info("⚠️ 该消息已过期.")
        counts = 0
        errors = 0
        for cr in ChatRedirect.select().join(ChatLog).where(ChatLog.id == c.id).iterator():
            cr_uid = cr.to_user.uid
            try:
                await self.bot.pin_chat_message(cr_uid, cr.message, both_sides=True, disable_notification=True)
            except RPCError:
                errors += 1
            finally:
                counts += 1
        logger.trace(f"[gray50]消息置顶 ({sender.name}, {sender.id}): {counts-errors} / {counts} 成功.[/]")
        await info("✅ 消息已置顶")

    async def unpin(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.ADMIN:
            return await info("⚠️ 无权限进行取消置顶.")
        rm = message.reply_to_message
        if not rm:
            return await info("⚠️ 您需要回复需取消置顶的消息.")
        if not rm.from_user.id == sender.id:
            return await info("⚠️ 只能取消置顶您的消息.")
        c = ChatLog.get_or_none(message=rm.id)
        if not c:
            return await info("⚠️ 该消息已过期.")
        counts = 0
        errors = 0
        for cr in ChatRedirect.select().join(ChatLog).where(ChatLog.id == c.id).iterator():
            cr_uid = cr.to_user.uid
            try:
                await self.bot.unpin_chat_message(cr_uid, cr.message)
            except RPCError:
                errors += 1
            finally:
                counts += 1
        logger.trace(f"[gray50]消息取消置顶 ({sender.name}, {sender.id}): {counts-errors} / {counts} 成功.[/]")
        await info("✅ 消息已取消置顶")

    async def info(self, info: str, message: TM, reply: bool = False, time: int = 5):
        if reply:
            msg = await message.reply(
                info,
                disable_notification=True,
                disable_web_page_preview=True,
            )
        else:
            msg = await self.bot.send_message(
                message.from_user.id,
                info,
                disable_notification=True,
                disable_web_page_preview=True,
            )
        await asyncio.sleep(time)
        await msg.delete()

    async def ban(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.ADMIN:
            return await info("⚠️ 无权限进行封禁.")

        cmd = message.text.split(None, 1)
        try:
            _, uid = cmd
            rur, _ = await ControlBot().fetch_user(uid)
        except ValueError:
            if not message.reply_to_message:
                return await info("⚠️ 请回复对应消息以封禁.")
            rm = message.reply_to_message
            if not rm:
                return await info("⚠️ 您需要回复需封禁用户发出的消息.")
            if rm.from_user.id == self.bot.me.id:
                cr = ChatRedirect.get_or_none(message=rm.id)
                if not cr:
                    return await info("⚠️ 消息必须来自其他人.")
                rur = cr.chat.user
            else:
                return await info("⚠️ 消息必须来自其他人.")
        rur.role = UserRole.BANNED
        rur.save()

        logger.info(f"管理员进行了封禁 ({sender.name}, {sender.id}): {rur.uid}.")
        umms = {}
        counts = 0
        for c in ChatLog.select().join(User).where(User.id == rur.id).iterator():
            for cr in ChatRedirect.select().join(ChatLog).where(ChatLog.id == c.id).iterator():
                cr_uid = cr.to_user.uid
                if cr_uid == rur.uid:
                    continue
                if cr_uid in umms:
                    umms[cr_uid].append(cr.message)
                else:
                    umms[cr_uid] = [cr.message]
                counts += 1
        logger.trace(f"[gray50]共 {len(umms)} 个用户的 {counts} 条消息需要删除.[/]")

        errors = 0
        for uid, ms in umms.items():
            try:
                await self.bot.delete_messages(uid, ms)
            except RPCError:
                errors += 1
        logger.trace(f"[gray50]用户消息已删除 ({uid}): {counts-errors} / {counts} 成功.[/]")

        try:
            u = await self.bot.get_users(rur.uid)
            un = f"[{u.name}](tg://user?id={rur.uid})"
            if not un:
                un = f"[<已注销>](tg://user?id={rur.uid})"
        except BadRequest:
            un = "<未知>"
        prompt = f"🚫 已封禁并删除消息: {un}"
        await info(prompt, time=10)

    async def restrict(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.ADMIN:
            return await info("⚠️ 无权限进行禁言.")

        cmd = message.text.split(None, 2)
        try:
            _, uid, duration = cmd
            rur, _ = await ControlBot().fetch_user(uid)
        except ValueError:
            if not message.reply_to_message:
                return await info("⚠️ 请回复对应消息以禁言.")
            rm = message.reply_to_message
            if not rm:
                return await info("⚠️ 您需要回复需禁言用户发出的消息.")
            if rm.from_user.id == self.bot.me.id:
                cr = ChatRedirect.get_or_none(message=rm.id)
                if not cr:
                    return await info("⚠️ 消息必须来自其他人.")
                rur = cr.chat.user
            else:
                return await info("⚠️ 消息必须来自其他人.")
            try:
                _, duration = cmd
            except ValueError:
                return await info("⚠️ 您需要在命令中设置禁言时长.")

        try:
            td = parse_timedelta(duration)
        except AssertionError:
            return await info("⚠️ 无效时长, 参考: 2d 8h 10m")

        logger.info(f"管理员进行了禁言 ({sender.name}, {sender.id}): {rur.uid}.")
        until = datetime.now() + td
        ChatBan(user=rur, until=until).save()

        try:
            u = await self.bot.get_users(rur.uid)
            un = f"[{u.name}](tg://user?id={rur.uid})"
            if not un:
                un = f"[<已注销>](tg://user?id={rur.uid})"
        except BadRequest:
            un = "<未知>"

        prompt = f'🚫 已禁言: {un}\n⏱️ 解封时间: {until.strftime("%Y-%d-%b %H:%M:%S")}'
        await info(prompt, time=10)

    async def unrestrict(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.ADMIN:
            return await info("⚠️ 无权限进行解除禁言.")

        cmd = message.text.split(None, 1)
        try:
            _, uid = cmd
            rur, _ = await ControlBot().fetch_user(uid)
        except ValueError:
            if not message.reply_to_message:
                return await info("⚠️ 请回复对应消息以禁言.")
            rm = message.reply_to_message
            if not rm:
                return await info("⚠️ 您需要回复需解除禁言用户发出的消息.")
            if rm.from_user.id == self.bot.me.id:
                cr = ChatRedirect.get_or_none(message=rm.id)
                if not cr:
                    return await info("⚠️ 消息必须来自其他人.")
                rur = cr.chat.user
            else:
                return await info("⚠️ 消息必须来自其他人.")

        ban = ChatBan.get_or_none(user=rur)
        if ban:
            ban.until = datetime.now()
            ban.save()
            logger.info(f"管理员解除了禁言 ({sender.name}, {sender.id}): {rur.uid}.")
            try:
                u = await self.bot.get_users(rur.uid)
                un = f"[{u.name}](tg://user?id={rur.uid})"
                if not un:
                    un = f"[<已注销>](tg://user?id={rur.uid})"
            except BadRequest:
                un = "<未知>"
            return await info(f"🚫 已解除禁言: {un}", time=10)
        else:
            return await info("⚠️ 用户未被禁言.")

    async def process_message(self, client: Client, message: TM):
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if message.text and message.text.startswith("/"):
            await asyncio.sleep(5)
            await message.delete()
            self.set_conversation(message, ur, None)
            return
        conv = self.conversations.get(sender.id, None)
        if conv:
            status, data = conv
            try:
                if status == ConversationStatus.WAITING_EMOJI:
                    if not message.text:
                        await info("⚠️ 无效信息.")
                        return
                    m = "".join(e["emoji"] for e in emoji.emoji_list(str(message.text)))
                    if not m:
                        await info("⚠️ 非 Emoji 不能作为面具.")
                        return
                    if len(m) > 3:
                        await info("⚠️ 过长, 最大 3 个 Emoji.")
                        return
                    current = ChatCustom.get_or_none(user=ur)
                    if current:
                        current.role = m
                        current.save()
                    else:
                        ChatCustom(user=ur, role=m).save()
                    await info(f"✅ 成功设置面具, 您当前的面具是 {m}.")
                    await data.delete()
                    return
            finally:
                await message.delete()
                self.set_conversation(message, ur, None)
        if ur.role < UserRole.MEMBER:
            await info("⚠️ 抱歉, 您已被封禁.")
            return
        for ban in ChatBan.select().join(User).where(User.id == ur.id).iterator():
            if ban.until > datetime.now():
                await info(f"⚠️ 抱歉, 您已被禁言直到 {ban.until.strftime('%Y-%d-%b %H:%M:%S')}.")
                return
        if message.text and len(message.text) > 200 and ur.role < UserRole.ADMIN:
            await info(
                f"⚠️ 抱歉, {self.get_masked_name(sender)}, 您的信息过长, "
                + f"如需发送日志隐去隐私通过 [Github Issues](https://github.com/embykeeper/embykeeper/issues) 发送.",
                time=10,
            )
            logger.debug(f"发送过长消息被删除 ({sender.name}, {sender.id}): {truncate_str(message.text, 15)}")
            await asyncio.sleep(5)
            await message.delete()
            return
        has_msg = bool(ChatLog.get_or_none(user=ur))
        if not has_msg:
            key = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            event = asyncio.Event()
            self.verifications[key] = (sender.id, event)
            layout = [
                [
                    InlineKeyboardButton(
                        "✅ 已阅读",
                        callback_data=self.set_callback({"type": "verification", "key": key}),
                    )
                ]
            ]
            if ur.role > UserRole.MEMBER:
                layout.append([InlineKeyboardButton("💬 联系 PMBot", url="https://t.me/embykeeper_pm_bot")])
            vmsg = await self.bot.send_message(
                sender.id,
                self.chat_msg.format(user=sender.name),
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup(layout),
            )
            try:
                await asyncio.wait_for(event.wait(), timeout=120)
            except asyncio.TimeoutError:
                return
            else:
                logger.debug(f"用户已阅读须知 ({sender.name}, {sender.id}).")
            finally:
                await vmsg.delete()
        if ur.role == UserRole.CREATOR:
            role = "⭐"
            spec = f"{role} (开发者)"
            created = False
        else:
            custom = ChatCustom.get_or_none(user=ur)
            if custom:
                role = custom.role
                created = False
            else:
                try:
                    created, role = await self.unique_roles.get_role(ur)
                except RoleNotAvailable:
                    await info(f"⚠️ 抱歉, {self.get_masked_name(sender)}, 当前匿名沟通人数已满.")
                    await asyncio.sleep(5)
                    await message.delete()
                else:
                    if created:
                        logger.trace(f"[gray50]用户创建了面具 ({sender.name}, {sender.id}): {role}.[/]")
            if ur.role >= UserRole.ADMIN:
                spec = f"{role} (管理员)"
            elif ur.role > UserRole.MEMBER:
                spec = f"{role} (高级用户)"
            else:
                spec = f"{role} "
        if message.media:
            if message.caption:
                act = "发送了媒体并说"
            else:
                act = "发送了媒体"
        else:
            act = "说"
        async with self.lock_last_user:
            content = message.text or message.caption
            if not content:
                prompt = f"{spec} {act}."
            else:
                if self.last_user == sender.id:
                    prompt = content
                else:
                    prompt = f"{spec} {act}:\n{content}"
            if created:
                raw_prompt = prompt
                prompt = f"{self.get_masked_name(sender)} 接下来将以 {role} 为面具进行匿名交流.\n\n{prompt}"

            logger.trace(f'[gray50]用户请求发送消息 ({sender.name}, {sender.id}): {truncate_str(content, 15) if content else "<媒体>"}[/]')

            with db.atomic():
                chat = ChatLog(user=ur, message=message.id)
                chat.save()

                rchat = ChatRedirect(chat=chat, to_user=ur, message=message.id)
                rchat.save()

            rm = message.reply_to_message
            if rm:
                reply_rchat = ChatRedirect.get_or_none(to_user=ur, message=rm.id)
                reply_chat = reply_rchat.chat if reply_rchat else None
            else:
                reply_chat = None

            errors = 0
            counts = 0
            masked_messages = {}
            for rur in User.select().join(ChatLog).group_by(User).iterator():
                if rur.id == ur.id:
                    continue
                if rur.role < UserRole.MEMBER:
                    continue
                if reply_chat:
                    rc = ChatRedirect.get_or_none(chat=reply_chat, to_user=rur)
                else:
                    rc = None
                if not self.last_user == sender.id:
                    if ur.role == UserRole.CREATOR:
                        sticker = "CAACAgUAAxkDAAIYyGU7g6Bi2rLcpn5waawYb8mIKCHjAAKYCgACZlnhVXEX8FwO32SMHgQ"
                        await self.bot.send_sticker(rur.uid, sticker)
                try:
                    if message.text:
                        message.text = prompt
                        masked_message = await message.copy(
                            rur.uid,
                            reply_to_message_id=rc.message if rc else None,
                        )
                    else:
                        masked_message = await message.copy(
                            rur.uid,
                            caption=prompt,
                            reply_to_message_id=rc.message if rc else None,
                        )
                except RPCError:
                    errors += 1
                else:
                    masked_messages[rur] = masked_message
                    ChatRedirect(chat=chat, to_user=rur, message=masked_message.id).save()
                finally:
                    counts += 1

            self.last_user = sender.id

            logger.trace(f"[gray50]用户消息已传播 ({sender.name}, {sender.id}): {counts-errors} / {counts} 成功.[/]")
            await info(f"✅ 消息已发送 (您的面具是 {role})", time=2)

        if created:
            prompt = raw_prompt
            await asyncio.sleep(10)
            if chat.id in self.edit_ids:
                pass
            else:
                errors = 0
                counts = 0
                if message.text:
                    for rur, m in masked_messages.items():
                        try:
                            await m.edit_text(prompt)
                        except BadRequest:
                            errors += 1
                        finally:
                            counts += 1
                else:
                    for rur, m in masked_messages.items():
                        try:
                            await m.edit_caption(prompt)
                        except BadRequest:
                            errors += 1
                        finally:
                            counts += 1
                logger.trace(f"[gray50]用户消息固化 ({sender.name}, {sender.id}): {counts-errors} / {counts} 成功.[/]")

    def get_masked_name(self, user: TU):
        ufn = user.first_name
        uln = user.last_name
        uun = user.username
        if ufn and uln:
            if len(ufn) == 1:
                return "◼" * 2 + uln[-1]
            elif len(uln) == 1:
                return ufn[0] + "◼" * 2
            else:
                return ufn[0] + "◼ ◼" + uln[-1]
        elif ufn:
            return ufn[0] + "◼" * 2
        elif uln:
            return "◼" * 2 + uln[-1]
        elif uun and len(uun) > 2:
            return "@" + uun[0] + "◼" * 2 + uun[-1]
        else:
            return "◼" * 2

    async def edit_broadcasted_message(self, client: Client, message: TM):
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.MEMBER:
            return
        c = ChatLog.get_or_none(message=message.id)
        if not c:
            return

        self.edit_ids.append(c.id)

        counts = 0
        errors = 0
        header = None
        for cr in ChatRedirect.select().join(ChatLog).where(ChatLog.id == c.id).iterator():
            cr_uid = cr.to_user.uid
            if cr_uid == ur.uid:
                continue
            try:
                if not header:
                    m = await self.bot.get_messages(cr_uid, cr.message)
                    match = re.match("^(.+?) .*:", m.text or m.caption)
                    if match:
                        role = match.group(1)
                    else:
                        match = re.search("接下来将以 (.+) 为面具", m.text)
                        if match:
                            role = match.group(1)
                        else:
                            role = None
                    content = message.text or message.caption
                    if role:
                        if ur.role >= UserRole.ADMIN:
                            spec = f"{role} (管理员)"
                        elif ur.role > UserRole.MEMBER:
                            spec = f"{role} (高级用户)"
                        else:
                            spec = f"{role} "
                        if message.media:
                            if message.caption:
                                act = "发送了媒体并说"
                            else:
                                act = "发送了媒体"
                        else:
                            act = "说"
                        if not content:
                            prompt = f"{spec} {act} (已编辑)."
                        else:
                            prompt = f"{spec} {act} (已编辑):\n{content}"
                    else:
                        prompt = content
                await self.bot.edit_message_text(cr_uid, cr.message, prompt)
            except RPCError:
                errors += 1
            finally:
                counts += 1
        logger.trace(f"[gray50]用户消息修改 ({sender.name}, {sender.id}): {counts-errors} / {counts} 成功.[/]")

        await info("✅ 消息已修改", time=2)

    async def delete(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.MEMBER:
            await info("⚠️ 抱歉, 您已被封禁.")
            return
        if not message.reply_to_message:
            return await info("⚠️ 请回复对应消息以删除.")
        rm = message.reply_to_message
        if rm.from_user.id == sender.id:
            c = ChatLog.get_or_none(message=rm.id)
            if not c:
                await info("⚠️ 该消息已过期.")
                return
            counts = 0
            errors = 0
            for cr in ChatRedirect.select().join(ChatLog).where(ChatLog.id == c.id).iterator():
                cr_uid = cr.to_user.uid
                try:
                    await self.bot.delete_messages(cr_uid, cr.message)
                except RPCError:
                    errors += 1
                finally:
                    counts += 1
            logger.trace(f"[gray50]用户消息删除 ({sender.name}, {sender.id}): {counts-errors} / {counts} 成功.[/]")
            await info("✅ 消息已删除")
        elif rm.from_user.id == self.bot.me.id and ur.role >= UserRole.ADMIN:
            cr = ChatRedirect.get_or_none(to_user=ur, message=rm.id)
            if not cr:
                await info("⚠️ 该消息已过期.")
                return
            c = cr.chat
            counts = 0
            errors = 0
            for cr in ChatRedirect.select().join(ChatLog).where(ChatLog.id == c.id).iterator():
                cr_uid = cr.to_user.uid
                try:
                    await self.bot.delete_messages(cr_uid, cr.message)
                except RPCError:
                    errors += 1
                finally:
                    counts += 1
            logger.trace(f"[gray50]用户消息删除 ({sender.name}, {sender.id}): {counts-errors} / {counts} 成功.[/]")
            await info("✅ 消息已删除")
        else:
            return await info("⚠️ 不支持该消息.")

    async def setmask(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.PRIME:
            await info("⚠️ 该功能仅限高级用户使用.")
            return
        m = await message.reply("ℹ️ 请输入您想使用的 Emoji 面具:")
        self.set_conversation(m, ur, ConversationStatus.WAITING_EMOJI)

    def set_conversation(self, data, user: User, status: ConversationStatus = None):
        self.conversations[user.uid] = (status, data) if status else None

import asyncio
from datetime import datetime, timedelta
import random
import re
import string

import emoji
from pyrogram import filters, Client
from pyrogram.handlers import MessageHandler, InlineQueryHandler, CallbackQueryHandler
from pyrogram.enums import ChatType
from pyrogram.types import (
    Message as TM,
    User as TU,
    InlineQuery as TI,
    CallbackQuery as TC,
    ChatPermissions,
    BotCommand,
    InlineQueryResultArticle,
    ChatMember,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputTextMessageContent,
)
from pyrogram.errors import BadRequest, RPCError
from loguru import logger

from ..utils import async_partial, parse_timedelta, remove_prefix, truncate_str
from ..model import db, User, AnonymousLog, UserRole
from .base import Bot
from .control import ControlBot

logger = logger.bind(scheme="groupman")


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


class GroupmanBot(Bot):
    name = "embykeeper_groupman_bot"
    chat = "embykeeperchat"
    allowed_anonymous_title = ["开发者官方"]

    def __init__(self, *args, welcome_msg: str = None, chat_msg: str = None, **kw):
        super().__init__(*args, **kw)

        self.lock_last_user = asyncio.Lock()
        self.last_user: int = None
        self.last_welcome_msg: TM = None
        self.welcome_msg: str = welcome_msg.strip() if welcome_msg else ""
        self.chat_msg: str = chat_msg.strip() if chat_msg else ""
        self.unique_roles = UniqueRole()
        self.jobs = []
        self.verifications = {}
        self.callbacks = {}

    async def watch_member_list(self):
        logger.info("群成员轮询已启动.")
        last_member_count = 0
        last_uid_set = set()
        first_run = True
        while True:
            try:
                c = await self.bot.get_chat_members_count(self.chat)
                if not c == last_member_count:
                    last_member_count = c
                    us = set()
                    m: ChatMember
                    async for m in self.bot.get_chat_members(self.chat):
                        if m.user:
                            us.add(m.user.id)
                    joining = us.difference(last_uid_set)
                    leaving = last_uid_set.difference(us)
                    last_uid_set = us

                    if first_run:
                        logger.trace(f"首次检查用户, 共 {len(last_uid_set)} 个用户.")
                        first_run = False
                        continue
                    else:
                        logger.trace(f"共 {len(joining)} 个用户加入, {len(leaving)} 个用户退出.")

                    if joining:
                        joining_users_spec = []
                        for j in joining:
                            user = await self.bot.get_users(j)
                            joining_users_spec.append(self.get_masked_name(user))
                        joining_users_spec = truncate_str(", ".join(joining_users_spec), 20)
                        if self.welcome_msg:
                            welcome_msg = await self.bot.send_message(
                                self.chat,
                                self.welcome_msg.format(user=joining_users_spec),
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
                            await asyncio.sleep(1)
                        if self.last_welcome_msg:
                            await self.last_welcome_msg.delete()
                        self.last_welcome_msg = welcome_msg

                    for l in leaving:
                        logger.info(f"用户 ({l}) 退群.")
            finally:
                await asyncio.sleep(1.5)

    async def setup(self):
        self.jobs.append(asyncio.create_task(self.watch_member_list()))
        await self.bot.set_bot_commands(
            [
                BotCommand("start", "显示当前匿名角色"),
                BotCommand("delete", "删除回复的匿名信息"),
                BotCommand("change", "更改匿名面具"),
                BotCommand("restrict", "(管理员) 禁言 [用户] [时长] [原因]"),
                BotCommand("ban", "(管理员) 封禁 [用户] [原因]"),
                BotCommand("reveal", "(管理员) 揭示 [链接]"),
            ]
        )
        group = filters.chat(self.chat)
        self.bot.add_handler(CallbackQueryHandler(self.callback))
        self.bot.add_handler(InlineQueryHandler(self.inline))
        self.bot.add_handler(MessageHandler(self.start, filters.command("start")))
        self.bot.add_handler(MessageHandler(self.delete, group & filters.command("delete")))
        self.bot.add_handler(MessageHandler(self.change, group & filters.command("change")))
        self.bot.add_handler(MessageHandler(self.restrict, group & filters.command("restrict")))
        self.bot.add_handler(MessageHandler(self.ban, group & filters.command("ban")))
        self.bot.add_handler(MessageHandler(self.reveal, filters.command("reveal")))
        self.bot.add_handler(MessageHandler(self.process_message, ~filters.service))
        logger.info(f"已启动监听: {self.bot.me.username}.")

    async def change(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        if sender:
            ur, _ = await ControlBot().fetch_user(sender)
        else:
            return await info("⚠️ 匿名管理员没有匿名面具.")
        _, role = await self.unique_roles.get_role(ur, renew=True)
        return await info(f"🌈 您好 {self.get_masked_name(sender)}!\n您已更换身份, 当前身份是: {role}")

    async def callback(self, client: Client, callback: TC):
        data = self.callbacks[callback.data]
        if data["type"] == "verification":
            uid, event = self.verifications.pop(data["key"])
            event.set()
            await callback.answer("⭐ 成功")
            return await self.bot.send_message(
                callback.from_user.id,
                "⭐ 已验证, 请回到群继续匿名聊天.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 回到群聊", url="https://t.me/embykeeperchat")]]),
            )

    async def reveal(self, client: Client, message: TM):
        info = async_partial(self.info, message=message)
        if not message.chat.type == ChatType.PRIVATE:
            await message.delete()
            return await info("⚠️ 该命令仅管理员私聊使用.")
        sender = message.from_user
        ur, _ = await ControlBot().fetch_user(sender)
        if ur.role < UserRole.ADMIN:
            return await info("⚠️ 无权限进行身份揭示.")
        cmd = message.text.split(None, 1)
        try:
            _, url = cmd
        except ValueError:
            return await info("⚠️ 缺少参数: 要揭示消息的链接.")
        match = re.match(f"https://t.me/{self.chat}/(\d+)", url)
        if not match:
            return await info("⚠️ 消息链接不合法.")
        try:
            msg = await self.bot.get_messages(self.chat, int(match.group(1)))
        except BadRequest:
            return await info("⚠️ 未找到该消息.")
        if not msg.from_user:
            return await info("⚠️ 无法揭示匿名管理员.")
        if msg.from_user.id == self.bot.me.id:
            log = AnonymousLog.get(AnonymousLog.masked_message == msg.id)
            uid = log.user.uid
        else:
            return await info("⚠️ 消息必须来自匿名者.")
        rur = User.get_or_none(uid=uid)
        if not rur:
            return await info("⚠️ 该用户未注册.")
        msg_count = AnonymousLog.select().where(AnonymousLog.user == rur).count()
        try:
            u = await self.bot.get_users(uid)
            un = f"[{u.name}](tg://user?id={uid})"
            if not un:
                un = f"[<已注销>](tg://user?id={uid})"
        except BadRequest:
            un = "<未知>"
        return await message.reply(
            "\n".join(
                [
                    f"用户名称: {un}",
                    f"用户 ID: `{uid}`",
                    f"等级状态: {rur.role.name}",
                    f"发言条数: {msg_count}",
                    f"注册时间: {rur.created.strftime('%Y-%m-%d')}",
                ]
            )
        )

    async def delete(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        if not sender:
            return await info("⚠️ 匿名管理员请直接删除信息.")
        if not message.reply_to_message:
            return await info("⚠️ 请回复对应消息以删除.")
        rm = message.reply_to_message
        if rm.from_user and rm.from_user.id == self.bot.me.id:
            log = AnonymousLog.get_or_none(masked_message=rm.id)
            if not log:
                return await info("⚠️ 匿名消息已失效.")
            uid = log.user.uid
            if not uid == sender.id:
                return await info("⚠️ 该命令仅可用于来源于您的匿名信息.")
            else:
                try:
                    await rm.delete()
                    return await info("🗑️ 已成功删除.")
                except RPCError as e:
                    logger.warning(f"删除时错误 ({uid}): {e.__class__.__name__}: {e}")
                    return await info(f"⚠️ 删除失败 ({uid}): {e.__class__.__name__}.")
        else:
            return await info("⚠️ 该命令仅可用于匿名消息.")

    async def inline(self, client: Client, inline_query: TI):
        sender = inline_query.from_user
        if sender and inline_query.query:
            ur, _ = await ControlBot().fetch_user(sender)
        else:
            return await inline_query.answer([], is_personal=True)
        role = await self.unique_roles.role_for(ur)
        if role:
            prompt = f"您的消息将以 {role} 身份匿名发送:"
        else:
            prompt = f"您的消息将匿名发送:"
        await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    title=prompt,
                    description=inline_query.query,
                    input_message_content=InputTextMessageContent(inline_query.query),
                )
            ],
            cache_time=60,
            is_personal=True,
        )

    def set_callback(self, data):
        key = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        self.callbacks[key] = data
        return key

    async def start(self, client: Client, message: TM):
        sender = message.from_user
        if message.chat.type == ChatType.PRIVATE:
            cmds = message.text.split()
            if len(cmds) == 2:
                if cmds[1].startswith("__v_"):
                    key = remove_prefix(cmds[1], "__v_")
                    if key not in self.verifications:
                        return await message.reply(sender.id, "⚠️ 验证已失效.")
                    uid, event = self.verifications[key]
                    if not uid == sender.id:
                        return await message.reply(sender.id, "⚠️ 请勿使用其他人的验证链接.")
                    ur, _ = await ControlBot().fetch_user(sender)
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
                    return await self.bot.send_message(
                        sender.id,
                        self.chat_msg.format(user=sender.name),
                        disable_web_page_preview=True,
                        reply_markup=InlineKeyboardMarkup(layout),
                    )
            else:
                return await self.bot.send_message(sender.id, "您好! 这里是 Emby 自动签到 群管理和匿名者 Bot!")
        else:
            info = async_partial(self.info, message=message)
            await message.delete()
            if sender:
                ur, _ = await ControlBot().fetch_user(sender)
            else:
                return await info(f"⚠️ 匿名管理员无法使用匿名功能.")
            _, role = await self.unique_roles.get_role(ur)
            return await info(f"🌈 您好 {self.get_masked_name(sender)}!\n您当前身份是: {role}")

    async def info(self, info: str, message: TM = None):
        if message:
            msg = await message.reply(
                info,
                disable_notification=True,
                disable_web_page_preview=True,
            )
        else:
            msg = await self.bot.send_message(
                self.chat,
                info,
                disable_notification=True,
                disable_web_page_preview=True,
            )
        await asyncio.sleep(5)
        await msg.delete()

    async def has_ban_right(self, user: TU):
        member = await self.bot.get_chat_member(self.chat, user.id)
        if member.privileges:
            return member.privileges.can_restrict_members
        else:
            return False

    async def ban(self, client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, message=message)
        sender = message.from_user
        if not sender:
            if not message.author_signature in self.allowed_anonymous_title:
                return await info("⚠️ 匿名管理员无法进行封禁.")
        elif not await self.has_ban_right(sender):
            return await info("⚠️ 无权限进行封禁.")
        cmd = message.text.split(None, 2)
        try:
            _, uid, reason = cmd
        except ValueError:
            if not message.reply_to_message:
                return await info("⚠️ 请回复对应消息以封禁.")
            rm = message.reply_to_message
            if not rm.from_user:
                return await info("⚠️ 无法封禁匿名管理员.")
            if rm.from_user.is_bot:
                return await info("⚠️ 无法限制机器人.")
            if rm.from_user.id == self.bot.me.id:
                log = AnonymousLog.get_or_none(masked_message=rm.id)
                if not log:
                    return await info("⚠️ 匿名消息已失效.")
                uid = log.user.uid
            else:
                uid = rm.from_user.id
            try:
                _, reason = cmd
            except ValueError:
                reason = None
        try:
            with db.atomic():
                await client.ban_chat_member(self.chat, uid)
                ur, _ = await ControlBot().fetch_user(uid)
                ur.role = UserRole.BANNED
                ur.save()
            masked_messages = []
            for log in AnonymousLog.select().join(User).where(User.uid == uid).iterator():
                masked_messages.append(log.masked_message)
            await client.delete_messages(self.chat, masked_messages)
            user = await self.bot.get_users(uid)
            prompt = f"🚫 已封禁并删除消息: {self.get_masked_name(user)}"
            if reason:
                prompt += f"\n⭐ 原因: {reason}"
            await message.reply(prompt)
        except RPCError as e:
            logger.warning(f"封禁时错误 ({uid}): {e.__class__.__name__}: {e}")
            return await info(f"⚠️ 封禁失败 ({uid}): {e.__class__.__name__}.")

    async def restrict(self, client: Client, message: TM):
        info = async_partial(self.info, message=message)
        sender = message.from_user
        if not sender:
            if not message.author_signature in self.allowed_anonymous_title:
                return await info("⚠️ 匿名管理员无法进行禁言.")
        elif not await self.has_ban_right(sender):
            return await info("⚠️ 无权限进行禁言.")
        cmd = message.text.split(None, 3)
        try:
            _, uid, duration, reason = cmd
        except ValueError:
            if not message.reply_to_message:
                return await info("⚠️ 请回复对应消息以禁言.")
            rm = message.reply_to_message
            if not rm.from_user:
                return await info("⚠️ 无法禁言匿名管理员.")
            if rm.from_user.is_bot:
                return await info("⚠️ 无法禁言机器人.")
            if rm.from_user.id == self.bot.me.id:
                log = AnonymousLog.get(masked_message=rm.id)
                if not log:
                    return await info("⚠️ 匿名消息已失效.")
                uid = log.user.uid
            else:
                uid = message.reply_to_message.from_user.id
            try:
                _, duration, reason = cmd
            except ValueError:
                try:
                    _, duration = cmd
                    reason = None
                except:
                    return await info("⚠️ 无效参数个数, 参考:\n/restrict 用户 时长 原因\n/restrict 时长 原因\n/restrict 时长")

        permissions = ChatPermissions(can_send_messages=False)
        try:
            td = parse_timedelta(duration)
        except AssertionError:
            return await info("⚠️ 无效时长, 参考: 2d 8h 10m")
        try:
            until = datetime.now() + td
            await self.bot.restrict_chat_member(self.chat, uid, permissions=permissions, until_date=until)
            user = await self.bot.get_users(uid)
            prompt = f'🚫 已禁言: {self.get_masked_name(user)}\n⏱️ 解封时间: {datetime.strftime(until, "%Y-%d-%b %H:%M:%S")}'
            if reason:
                prompt += f"\n⭐ 原因: {reason}"
            await message.reply(prompt)
        except RPCError as e:
            logger.warning(f"禁言时错误 ({uid}): {e.__class__.__name__}: {e}")
            return await info(f"⚠️ 禁言失败 ({uid}): {e.__class__.__name__}")

    async def process_message(self, client: Client, message: TM):
        info = async_partial(self.info, message=message)
        sender = message.from_user
        rm = message.reply_to_message
        if sender and not sender.is_bot:
            ur, _ = await ControlBot().fetch_user(sender)
        else:
            self.last_user = sender.id if sender else None
            if rm and not (sender and sender.is_bot):
                if rm.from_user and rm.from_user.id == self.bot.me.id:
                    log = AnonymousLog.get(masked_message=rm.id)
                    if log:
                        uid = log.user.uid
                        logger.trace(f"进行回复提醒: {uid}")
                        try:
                            text = message.text or message.caption
                            if text:
                                prompt = f"✉️ 您的匿名消息收到了一条新的回复:\n{text}"
                            else:
                                prompt = f"✉️ 您的匿名消息收到了一条新的多媒体回复."
                            await self.bot.send_message(
                                uid,
                                prompt,
                                reply_markup=InlineKeyboardMarkup(
                                    [[InlineKeyboardButton("💬 在群聊查看", url=message.link)]],
                                ),
                                disable_notification=True,
                            )
                        except RPCError:
                            pass
            return
        if message.text and message.text.startswith("/"):
            await asyncio.sleep(5)
            await message.delete()
            return
        else:
            await message.delete()
        if message.text and len(message.text) > 200:
            return await info(
                f"⚠️ 抱歉, {self.get_masked_name(sender)}, 您的信息过长, "
                + f"如需发送日志隐去隐私通过 [Github Issues](https://github.com/embykeeper/embykeeper/issues) 发送."
            )
        ur, _ = await ControlBot().fetch_user(sender)
        has_msg = bool(AnonymousLog.get_or_none(user=ur))
        if not has_msg:
            for uid, _ in self.verifications.values():
                if uid == sender.id:
                    return await info("⚠️ 请先验证才能发送信息.")
            key = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            event = asyncio.Event()
            self.verifications[key] = (sender.id, event)
            vmsg = await message.reply(
                f"ℹ️ 您好, {self.get_masked_name(sender)}, 这是您首次进行匿名交流, 请先验证.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⭐ 前往验证",
                                url=f"https://t.me/{self.bot.me.username}?start=__v_{key}",
                            )
                        ]
                    ]
                ),
            )
            try:
                await asyncio.wait_for(event.wait(), timeout=120)
            except asyncio.TimeoutError:
                return
            finally:
                await vmsg.delete()
        try:
            created, role = await self.unique_roles.get_role(ur)
        except RoleNotAvailable:
            return await info(f"⚠️ 抱歉, {self.get_masked_name(sender)}, 当前匿名沟通人数已满.")
        if ur.role >= UserRole.ADMIN:
            spec = f"{role} (管理员)"
        elif ur.role > UserRole.MEMBER:
            spec = f"{role} (高级用户)"
        else:
            spec = role
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
            self.last_user = sender.id
        if created:
            raw_prompt = prompt
            prompt = f"您好 {self.get_masked_name(sender)}!\n接下来您将以 {role} 为面具进行匿名交流.\n\n{prompt}"
        if message.text:
            message.text = prompt
            masked_message = await message.copy(
                self.chat,
                reply_to_message_id=rm.id if rm else None,
                disable_notification=True,
            )
        else:
            masked_message = await message.copy(
                self.chat,
                caption=prompt,
                reply_to_message_id=rm.id if rm else None,
                disable_notification=True,
            )
        AnonymousLog(user=ur, role=role, message=message.id, masked_message=masked_message.id).save()
        if rm and not (sender and sender.is_bot):
            if rm.from_user and rm.from_user.id == self.bot.me.id:
                log = AnonymousLog.get(masked_message=rm.id)
                if log:
                    uid = log.user.uid
                    logger.trace(f"进行回复提醒: {uid}")
                    try:
                        text = message.text or message.caption
                        if text:
                            prompt = f"✉️ 您的匿名消息收到了一条新的回复:\n{text}"
                        else:
                            prompt = f"✉️ 您的匿名消息收到了一条新的多媒体回复."
                        await self.bot.send_message(
                            uid,
                            prompt,
                            reply_markup=InlineKeyboardMarkup(
                                [[InlineKeyboardButton("💬 在群聊查看", url=masked_message.link)]],
                            ),
                            disable_notification=True,
                        )
                    except RPCError:
                        pass
        if created:
            try:
                prompt = raw_prompt
                if message.text:
                    await asyncio.sleep(10)
                    await masked_message.edit_text(prompt)
                else:
                    await asyncio.sleep(10)
                    await masked_message.edit_caption(prompt)
            except BadRequest:
                pass

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

import asyncio
import hashlib
from typing import Dict

from loguru import logger
from pyrogram import filters
from pyrogram.handlers import MessageHandler, EditedMessageHandler
from pyrogram.errors import UserDeactivated, RPCError
from pyrogram.types import BotCommand

from ...utils import truncate_str
from ...cache import Cache, CacheDict
from ...config import config
from ...model import UserRole, db, BanGroup, Group, User, Member, MemberRole
from ..base import MenuBot
from .mask import UniqueMask
from .worker import Worker, WorkerQueue
from .on_message import OnMessage
from .command import OnCommand
from .tree import Tree
from .start import Start
from .manage import Manage


class _Methods(Worker, Tree, OnMessage, OnCommand, Start, Manage):
    pass

class GroupBot(MenuBot, _Methods):
    def __init__(self, token: str, creator: User = None, booted: asyncio.Event = None) -> None:
        self.name = hashlib.sha1(token.encode()).hexdigest()[:8]
        super().__init__(token)
        self.booted = booted or asyncio.Event()
        self.failed = asyncio.Event()
        self.boot_exception = None
        self.log = logger.bind(scheme="group")
        self.unique_mask_pool = UniqueMask(self.token)
        self.lock = asyncio.Lock()
        self.user_locks: Dict[Member, asyncio.Lock] = {}
        self.queue = WorkerQueue(f'group.{self.token}.worker.queue', self.bot)
        self.worker_status = CacheDict(
            f'group.{self.token}.worker.status',
            default={
                'time': 0,
                'requests': 0,
                'errors': 0
            }
        )
        self.invite_codes = Cache(base=f'group.{self.token}.invite.code')
        self.jobs.append(self.worker())
        self.group: Group = Group.get_or_none(token=self.token)
        if self.group:
            self.creator = self.group.creator
        else:
            self.creator = creator

    async def start(self):
        try:
            try:
                await self.bot.start()
                await self.setup()
            except Exception as e:
                if isinstance(e, UserDeactivated):
                    if self.group:
                        self.group.disabled = True
                        self.group.save()
                        logger.info(f"Group @{self.group.username} disabled because token deactivated.")
                self.boot_exception = e
                return
            finally:
                self.tasks.extend([asyncio.create_task(j) for j in self.jobs])
                self.booted.set()
                self.log = self.log.bind(id=f'@{self.group.username}')
            await self.failed.wait()
        except asyncio.CancelledError:
            pass
        finally:
            for t in self.tasks:
                t.cancel()
            try:
                await self.bot.stop()
            except ConnectionError:
                pass
            except RPCError:
                pass
            else:
                if self.group:
                    logger.info(f"Stop listening updates in group: @{self.group.username}.")
                else:
                    logger.info(f"Stop listening updates in group with token {truncate_str(self.token, 20)}.")

    async def setup(self):
        common_filter = filters.private & (~filters.outgoing) & (~filters.bot) & (~filters.service)
        
        self.bot.add_handler(MessageHandler(self.on_message, common_filter))
        self.bot.add_handler(EditedMessageHandler(self.on_edit_message, common_filter))

        self.bot.add_handler(MessageHandler(self.on_delete, common_filter & filters.command("delete")))
        self.bot.add_handler(MessageHandler(self.on_change, common_filter & filters.command("change")))
        self.bot.add_handler(MessageHandler(self.on_setmask, common_filter & filters.command("setmask")))
        self.bot.add_handler(MessageHandler(self.on_ban, common_filter & filters.command("ban")))
        self.bot.add_handler(MessageHandler(self.on_unban, common_filter & filters.command("unban")))
        self.bot.add_handler(MessageHandler(self.on_pin, common_filter & filters.command("pin")))
        self.bot.add_handler(MessageHandler(self.on_unpin, common_filter & filters.command("unpin")))
        self.bot.add_handler(MessageHandler(self.on_reveal, common_filter & filters.command("reveal")))
        self.bot.add_handler(MessageHandler(self.on_manage, common_filter & filters.command("manage")))
        self.bot.add_handler(MessageHandler(self.on_pm, common_filter & filters.command("pm")))

        self.menu.setup(self.bot)

        self.bot.add_handler(MessageHandler(self.on_unknown, common_filter))

        await self.bot.set_bot_commands([BotCommand("start", "Open panel")])

        if not self.group:
            if not self.creator:
                raise ValueError("must specify creator for group creation")
            with db.atomic():
                self.group = Group.create(
                    uid=self.bot.me.id,
                    token=self.bot.bot_token,
                    username=self.bot.me.username,
                    title=self.bot.me.name,
                    creator=self.creator,
                    default_ban_group=BanGroup.generate(),
                )
                Member.create(group=self.group, user=self.creator, role=MemberRole.CREATOR)
                if not self.creator.validate(UserRole.GROUPER):
                    self.creator.add_role(UserRole.GROUPER)
                if self.creator.validate(UserRole.INVITED):
                    days = config.get('father.invite_award_days', 180)
                    self.creator.add_role(UserRole.AWARDED, days=days)
                    if self.creator.invited_by:
                        self.creator.invited_by.add_role(UserRole.AWARDED, days=days)
        logger.info(f"Now listening updates in group: @{self.bot.me.username}.")

        await self.bot.set_bot_commands(
            [
                BotCommand("start", "显示信息面板"),
                BotCommand("delete", "删除所回复的消息"),
                BotCommand("pm", "私聊所回复的成员"),
                BotCommand("change", "随机更改面具"),
                BotCommand("setmask", "设置面具"),
                BotCommand("invite", "创建邀请链接"),
                BotCommand("ban", "(管理/私聊) 封禁 [成员]"),
                BotCommand("unban", "(管理/私聊) 解封 [成员]"),
                BotCommand("pin", "(管理) 置顶所回复的消息"),
                BotCommand("unpin", "(管理) 取消置顶所回复的消息"),
                BotCommand("reveal", "(管理) 揭示所回复成员信息"),
                BotCommand("manage", "(管理) 管理所回复的成员"),
            ]
        )

    async def touch(self):
        if self.group:
            self.group.username = self.bot.me.username
            self.group.title = self.bot.me.name
            self.group.save()
            self.group.touch()
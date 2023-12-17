import asyncio
from pyrogram import Client
from pyrogram.types import Message as TM, CallbackQuery as TC, InlineKeyboardButton, InlineKeyboardMarkup

import anonyabbot

from ...model import BanType, Member, User, MemberRole
from ...utils import async_partial, remove_prefix
from .worker import BulkRedirectOperation, BulkPinOperation
from .common import operation


class Start:
    async def send_welcome_msg(self: "anonyabbot.GroupBot", user: User, msg: str = None, button_spec: str = None, photo: str = None):
        if msg:
            msg = msg.format(
                first_name=user.firstname,
                last_name=user.lastname,
                masked_name=user.masked_name,
                name=user.name,
                markdown=user.markdown,
            )
        else:
            msg = (
                f"🌈 欢迎加入匿名群组 **{self.group.title}**!\n\n"
                "所有发送给机器人的消息都将被转发给所有成员, 您的身份被隐藏. \n"
                "您将使用一个 emoji 作为您的面具进行聊天.\n"
                "只有管理员才能看到您面具背后的真实身份.\n"
                "请开始化妆舞会吧!"
            )
        
        if not 'anonycnbot' in msg:
            msg += '\n\n本机器人由 [@anonycnbot](t.me/anonycnbot) 创建.'

        if button_spec:
            keyboard = []
            for l in button_spec.splitlines():
                line = []
                for b in l.split("|"):
                    display, url = b.split(":", 1)
                    display = display.strip()
                    url = url.strip()
                    button = InlineKeyboardButton(display, url=url)
                    line.append(button)
                keyboard.append(line)
            markup = InlineKeyboardMarkup(keyboard)
        else:
            markup = None

        if photo:
            return await self.bot.send_photo(user.uid, photo, caption=msg, reply_markup=markup)
        else:
            return await self.bot.send_message(user.uid, msg, reply_markup=markup)
        
    async def send_latest_messages(self: "anonyabbot.GroupBot", member: Member, context: TM):
        if self.group.welcome_latest_messages:
            nrpm = member.not_redirected_pinned_messages()
            if len(nrpm) > 0:
                e = asyncio.Event()
                op = BulkRedirectOperation(messages=reversed(nrpm), member=member, finished=e)
                info = async_partial(self.info, context=context)
                msg: TM = await info(f"🔃 加载置顶消息 ...", time=None)
                await self.queue.put(op)
                try:
                    await asyncio.wait_for(e.wait(), 120)
                except asyncio.TimeoutError:
                    await msg.edit("⚠️ 加载置顶消息超时.")
                    await asyncio.sleep(3)
                await msg.delete()
            
                e = asyncio.Event()
                op = BulkPinOperation(messages=reversed(list(member.pinned_messages())), member=member, finished=e)
                info = async_partial(self.info, context=context)
                msg: TM = await info(f"🔃 设置置顶消息 ...", time=None)
                await self.queue.put(op)
                try:
                    await asyncio.wait_for(e.wait(), 120)
                except asyncio.TimeoutError:
                    await msg.edit("⚠️ 设置置顶消息超时.")
                    await asyncio.sleep(3)
                await msg.delete()
                
            nrm = member.not_redirected_messages()
            if len(nrm) > 0:
                e = asyncio.Event()
                op = BulkRedirectOperation(messages=reversed(nrm), member=member, finished=e)
                info = async_partial(self.info, context=context)
                msg: TM = await info(f"🔃 加载最新消息 ...", time=None)
                await self.queue.put(op)
                try:
                    await asyncio.wait_for(e.wait(), 120)
                except asyncio.TimeoutError:
                    await msg.edit("⚠️ 加载最新消息超时.")
                    await asyncio.sleep(3)
                await msg.edit_text('💬 最新消息:')
            

    @operation(req=None, concurrency='queue')
    async def on_start(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TM,
        parameters: dict,
    ):
        async def welcome(self: "anonyabbot.GroupBot", user: User, member: Member, context: TM):
            await self.send_welcome_msg(
                user=user,
                msg=self.group.welcome_message,
                button_spec=self.group.welcome_message_buttons,
                photo=self.group.welcome_message_photo,
            )
            await self.send_latest_messages(
                member=member,
                context=context,
            )
        
        async def check(self: "anonyabbot.GroupBot", member: Member, context: TM):
            info = async_partial(self.info, context=context)
            if self.group.private:
                content = context.text or context.caption
                cmds = content.split()
                if len(cmds) == 2:
                    if cmds[1].startswith("_c_"):
                        code = remove_prefix(cmds[1], "_c_")
                        try:
                            invitor: Member
                            invitor, usage = self.invite_codes.get(code)
                        except KeyError:
                            await info('🚫 这个邀请链接已失效')
                            return False
                        else:
                            if usage <= 0:
                                await info('🚫 这个邀请链接已失效')
                                return False
                            if invitor.check_ban(BanType.INVITE):
                                await info('🚫 这个邀请链接已失效')
                                return False
                            member.invitor = invitor
                            usage -= 1
                            self.invite_codes.set(code, (invitor, usage), ttl=-1)
                            return True
                    else:
                        await info('🚫 这是一个私有群组，只能通过邀请链接加入')
                        return False
                else:
                    await info('🚫 这是一个私有群组，只能通过邀请链接加入')
                    return False
            elif self.group.password:
                event = asyncio.Event()
                container = [False]
                self.set_conversation(context, "gp_password", (event, container))
                imsg = await self.bot.send_message(context.from_user.id, 'ℹ️ 输入群组密码以加入：')
                try:
                    await asyncio.wait_for(event.wait(), timeout=120)
                except asyncio.TimeoutError:
                    await info('🚫 超时')
                    return False
                else:
                    if container[0]:
                        await info('✅ 密码正确')
                        return True
                    else:
                        await info('🚫 密码错误的')
                        return False
                finally:
                    await imsg.delete()
                    await context.delete()
            else:
                return True
        
        content = context.text or context.caption       
        if not content.startswith('/start'):
            context.continue_propagation()
        member: Member = context.from_user.get_member(self.group)
        user: User = context.from_user.get_record()
        if member:
            if isinstance(context, TM):
                await context.delete()
            mask = member.pinned_mask or await self.unique_mask_pool.mask_for(member)
            if member.role == MemberRole.LEFT:
                if await check(self, member, context):
                    member.role = MemberRole.GUEST
                    member.save()
                    await welcome(self, user, member, context)
            else:
                return (
                    "ℹ️ 该群组由 @anonycnbot 创建.\n"
                    "🌈 群组状态：\n\n"
                    f"成员数：{self.group.n_members}\n"
                    f"非游客成员数：{self.group.s_all_has_role(MemberRole.MEMBER).count()}\n\n"
                    "👤 您的成员信息：\n\n"
                    f"权限身份：{member.role.display.title()}\n"
                    f'面具：{mask if mask else "<未激活>"}\n\n'
                    f"👁️‍🗨️ 此面板仅对您可见. "
                )
        else:
            if await check(self, member, context):
                member = Member.create(group=self.group, user=user, role=MemberRole.GUEST)
                await welcome(self, user, member, context)

    @operation()
    async def on_leave_group_confirm(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        member: Member = context.from_user.get_member(self.group)
        if member.role == MemberRole.CREATOR:
            await context.answer("⚠️ Creator of the group cannot leave.", show_alert=True)
            await self.to_menu("start", context)
            return
        return f"⚠️ 你确定要退出这个群组?\n⚠️ 你当前的权限角色是: {member.role.display}."

    @operation()
    async def on_leave_group(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        member: Member = context.from_user.get_member(self.group)
        member.role = MemberRole.LEFT
        member.save()
        await context.answer("✅ 您已退出群组, 将不再收到消息.", show_alert=True)
        await asyncio.sleep(2)
        await context.message.delete()
        return

    @operation(MemberRole.ADMIN)
    async def on_manage_group(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        await self.to_menu("_group_details", context)

    @operation(req=None)
    async def on_close_start(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        await context.message.delete()
        await context.answer()

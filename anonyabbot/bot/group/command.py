import asyncio
import random
import string
from pyrogram import Client
from pyrogram.types import Message as TM, CallbackQuery as TC
from pyrogram.errors import RPCError
from pyrubrum import Element

import anonyabbot

from ...model import MemberRole, Member, OperationError, BanType, Message, PMBan, PMMessage, RedirectedMessage, User
from ...utils import async_partial, parse_timedelta
from .common import operation
from .worker import DeleteOperation, PinOperation, UnpinOperation
from .mask import MaskNotAvailable


class OnCommand:
    def get_member_reply_message(self: "anonyabbot.GroupBot", message: TM, allow_pm=False):
        member: Member = message.from_user.get_member(self.group)
        rm = message.reply_to_message
        if not rm:
            raise OperationError("没有回复消息")
        mr: Message = Message.get_or_none(mid=rm.id, member=member)
        if not mr:
            rmr = RedirectedMessage.get_or_none(mid=rm.id, to_member=member)
            if rmr:
                mr: Message = rmr.message
            else:
                if allow_pm:
                    pmm: PMMessage = PMMessage.get_or_none(redirected_mid=rm.id, to_member=member)
                    if pmm:
                        mr: PMMessage = pmm
                    else:
                        raise OperationError("这不是匿名消息或已过时")
                else:
                    raise OperationError("这不是匿名消息或已过时")
        return member, mr

    @operation(MemberRole.MEMBER)
    async def on_delete(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        member, mr = self.get_member_reply_message(message)
        member.check_ban(BanType.MESSAGE)
        if not mr.member.id == member.id:
            if not member.validate(MemberRole.ADMIN_BAN):
                return await info(f"⚠️ 只能删除您发送的消息")
        e = asyncio.Event()
        op = DeleteOperation(member=member, finished=e, message=mr)
        await self.queue.put(op)
        msg: TM = await info(f"🔃 正在删除该消息...", time=None)
        n_members = self.group.n_members
        for i in range(30 + 5 * n_members):
            try:
                await asyncio.wait_for(e.wait(), 1)
            except asyncio.TimeoutError:
                pass
            else:
                await msg.edit(f"🗑️ 消息已删除 ({op.requests-op.errors}/{op.requests} 成功).")
                break
            if i and (i % 10 == 0):
                await msg.edit(f"🔃 正在删除该消息 ({op.requests}/{n_members}) ...")
        else:
            await msg.edit("⚠️ 删除该消息超时")
        await asyncio.sleep(2)
        await msg.delete()

    @operation(MemberRole.MEMBER)
    async def on_change(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        member: Member = message.from_user.get_member(self.group)
        _, mask = await self.unique_mask_pool.get_mask(member, renew=True)
        await info(f"🌈 你的面具已更改为: {mask}")

    @operation(MemberRole.MEMBER)
    async def on_setmask(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        member: Member = message.from_user.get_member(self.group)
        if not member.validate(MemberRole.ADMIN):
            if not member.user.is_prime:
                await info(f"⚠️ 您需要 [PRIME](t.me/anonycnbot?start=_createcode) 特权以使用该功能.")
                return
        msg: TM = await info("⬇️ 请输入 emoji 作为您的面具:", time=None)
        self.set_conversation(message, "sm_mask", data=msg)
        await asyncio.sleep(120)
        if await msg.delete():
            self.set_conversation(message, None)
            await info("⚠️ 会话超时", time=2)

    @operation()
    async def on_ban(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)

        cmd = message.text.split(None, 1)
        try:
            _, uid = cmd
        except ValueError:
            member, mr = self.get_member_reply_message(message, allow_pm=True)
            if isinstance(mr, Message):
                target = mr.member
            elif isinstance(mr, PMMessage):
                target = mr.from_member
                pmban = PMBan.get_or_none(from_member=target, to_member=member)
                if not pmban:
                    PMBan.create(from_member=target, to_member=member)
                return await info("✅ 该成员给您发的私信将被屏蔽")
        else:
            user = await self.bot.get_users(uid)
            target = user.get_member(self.group)
            if not target:
                raise OperationError("成员已不在群组中")
            member: Member = message.from_user.get_member(self.group)
        member.validate(MemberRole.ADMIN_BAN)
        if target.role >= MemberRole.ADMIN:
            member.validate(MemberRole.ADMIN_ADMIN, fail=True)
        if target.role >= MemberRole.ADMIN_ADMIN:
            member.validate(MemberRole.CREATOR, fail=True)
        if target.id == member.id:
            return await info("⚠️ 不能封禁自己")
        if target.role >= member.role:
            return await info("⚠️ 您的权限低于对方权限")
        if target.role == MemberRole.BANNED:
            return await info("⚠️ 该成员本就处于封禁状态")

        target.role = MemberRole.BANNED
        target.save()
        return await info("🚫 成员已封禁")

    @operation()
    async def on_unban(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)

        cmd = message.text.split(None, 1)
        try:
            _, uid = cmd
        except ValueError:
            member, mr = self.get_member_reply_message(message, allow_pm=True)
            if isinstance(mr, Message):
                target = mr.member
            elif isinstance(mr, PMMessage):
                target = mr.from_member
                pmban = PMBan.get_or_none(from_member=target, to_member=member)
                if pmban:
                    pmban.delete_instance()
                return await info("✅ 此成员现在可以发送私人消息给您了")
        else:
            user = await self.bot.get_users(uid)
            target = user.get_member(self.group)
            if not target:
                raise OperationError("成员已不在群组中")
            member: Member = message.from_user.get_member(self.group)
        member.validate(MemberRole.ADMIN_BAN)
        if target.role >= MemberRole.ADMIN:
            member.validate(MemberRole.ADMIN_ADMIN, fail=True)
        if target.role >= MemberRole.ADMIN_ADMIN:
            member.validate(MemberRole.CREATOR, fail=True)
        if target.id == member.id:
            return await info("⚠️ 无法解封自己")
        if target.role >= member.role:
            return await info("⚠️ 您的权限低于对方权限")
        if not target.role == MemberRole.BANNED:
            return await info("⚠️ 该用户未被封禁")


        target.role = MemberRole.GUEST
        target.save()
        return await info("✅ 成员已解封")

    @operation(MemberRole.ADMIN_MSG)
    async def on_pin(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        user: User = message.from_user.get_record()
        if (not self.group.is_prime) and (not user.is_prime):
            await info(f"⚠️ 您或该群组创建者没有 [PRIME](t.me/anonycnbot?start=_createcode) 特权, 因此不能使用该功能.")
            return
        member, mr = self.get_member_reply_message(message)
        mr.pinned = True
        mr.save()
        e = asyncio.Event()
        op = PinOperation(member=member, finished=e, message=mr)
        await self.queue.put(op)
        msg: TM = await info(f"🔃 正在置顶消息...", time=None)
        n_members = self.group.n_members
        for i in range(30 + 5 * n_members):
            try:
                await asyncio.wait_for(e.wait(), 1)
            except asyncio.TimeoutError:
                pass
            else:
                await msg.edit(f"📌 消息已置顶 ({op.requests-op.errors}/{op.requests} 成功).")
                break
            if i and (i % 10 == 0):
                await msg.edit(f"🔃 正在置顶消息 ({op.requests}/{n_members}) ...")
        else:
            await msg.edit("⚠️ 置顶消息超时")
        await asyncio.sleep(2)
        await msg.delete()

    @operation(MemberRole.ADMIN_MSG)
    async def on_unpin(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        if not self.group.is_prime:
            await info(f"⚠️ 该群组创建者没有 [PRIME](t.me/anonycnbot?start=_createcode) 特权, 因此不能使用该功能.")
            return
        member, mr = self.get_member_reply_message(message)
        mr.pinned = False
        mr.save()
        e = asyncio.Event()
        op = UnpinOperation(member=member, finished=e, message=mr)
        await self.queue.put(op)
        msg: TM = await info(f"🔃 正在取消置顶消息...", time=None)
        n_members = self.group.n_members
        for i in range(30 + 5 * n_members):
            try:
                await asyncio.wait_for(e.wait(), 1)
            except asyncio.TimeoutError:
                pass
            else:
                await msg.edit(f"📌 消息已取消置顶 ({op.requests-op.errors}/{op.requests} 成功).")
                break
            if i and (i % 10 == 0):
                await msg.edit(f"🔃 正在取消置顶消息 ({op.requests}/{n_members}) ...")
        else:
            await msg.edit("⚠️ 取消置顶消息超时")
        await asyncio.sleep(2)
        await msg.delete()

    @operation(MemberRole.ADMIN_BAN)
    async def on_reveal(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        _, mr = self.get_member_reply_message(message)
        target: Member = mr.member
        msg = (
            f"ℹ️ 此成员的信息:\n\n"
            f"姓名: {target.user.name}\n"
            f"ID: {target.user.uid}\n"
            f"群组中的角色: {target.role.display.title()}\n"
            f"加入日期: {target.created.strftime('%Y-%m-%d')}\n"
            f"消息总数: {target.n_messages}\n"
            f"最近活跃: {target.last_activity.strftime('%Y-%m-%d')}\n"
            f"最近面具: {target.last_mask}\n\n"
            f"👁️‍🗨️ 这个面板仅对您可见"
        )
        await info(msg, time=15)

    @operation(MemberRole.ADMIN_BAN)
    async def on_manage(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        _, mr = self.get_member_reply_message(message)
        target: Member = mr.member
        return await self.to_menu_scratch("_member_detail", message.chat.id, message.from_user.id, member_id=target.id)

    async def pm(self, message: TM):
        info = async_partial(self.info, context=message, block=False)
        binfo = async_partial(self.info, context=message)

        content = message.text or message.caption
        
        try:
            member, mr = self.get_member_reply_message(message, allow_pm=True)
            if isinstance(mr, Message):
                target: Member = mr.member
            elif isinstance(mr, PMMessage):
                target: Member = mr.from_member
            member.check_ban(BanType.PM_USER)
            if target.role >= MemberRole.ADMIN:
                member.check_ban(BanType.PM_ADMIN)
            if target.role <= MemberRole.LEFT:
                raise OperationError('成员已不在群组中')
            if target.check_ban(BanType.RECEIVE, check_group=False, fail=False):
                raise OperationError('此用户被禁止接收消息')
            pmban = PMBan.get_or_none(from_member=member, to_member=target)
            if pmban:
                raise OperationError('此用户不想接收来自您的私信')
            self.check_message(message, member)
        except OperationError as e:
            await binfo(f"⚠️ 对不起, {e}, 此消息将被删除. ", time=30)
            await message.delete()
            return
        
        if member.pinned_mask:
            mask = member.pinned_mask
            created = False
        else:
            try:
                created, mask = await self.unique_mask_pool.get_mask(member)
            except MaskNotAvailable:
                await binfo(f"⚠️ 对不起, 目前没有可用的面具, 请尝试手动设置面具, 此消息将被删除. ", time=30)
                await message.delete()
                return
        
        content = f'{mask} (👁️ PM) | {content}'
        
        if created:
            msg: TM = await info(f"🔃 正在以 {mask} 为面具发送私信...", time=None)
        else:
            msg: TM = await info("🔃 正在发送私信...", time=None)
        
        try:
            if message.text:
                message.text = content
                masked_message = await message.copy(target.user.uid)
            else:
                masked_message = await message.copy(target.user.uid, caption=content)
        except RPCError as e:
            await msg.edit('⚠️ 发送失败, 此消息将被删除. ')
            await asyncio.sleep(30)
            await msg.delete()
            return
        else:
            PMMessage.create(from_member=member, to_member=target, mid=message.id, redirected_mid=masked_message.id)
            await msg.edit('✅ 私信已发送')
            await asyncio.sleep(5)
            await msg.delete()


    @operation(MemberRole.MEMBER)
    async def on_pm(self: "anonyabbot.GroupBot", client: Client, message: TM):
        info = async_partial(self.info, context=message)
        
        content = message.text or message.caption
        
        cmd = content.split(None, 1)
        try:
            _, content = cmd
        except ValueError:
            await message.delete()
            return await info('⚠️ 使用 "/pm [text]" 发送私信')
        
        message.text = content

        await self.pm(message)
        
    @operation(MemberRole.MEMBER)
    async def on_invite(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TM,
        parameters: dict,
    ):
        await context.delete()
        if not self.group.private:
            raise OperationError('该群组是公开群组, 不需要邀请链接')
        member: Member = context.from_user.get_member(self.group)
        member.check_ban(BanType.INVITE, fail=True)
        return '❓ 生成的邀请链接可以使用多少次?'
    
    @operation(None)
    async def on_close_invite(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        await context.message.delete()
    
    @operation(MemberRole.MEMBER)
    async def items_invite(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        return [Element(str(i), str(i)) for i in [1, 2, 3, 5, "无限"]]
    
    @operation(MemberRole.MEMBER)
    async def on_i_select_time(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        return '❓ 生成的邀请链接有效期是多长?'
    
    @operation(MemberRole.MEMBER)
    async def items_i_select_time(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        return [Element(i, i) for i in ["1m", "10m", "1h", "12h", "1d", "7d", "30d", "永久"]]
    
    @operation(MemberRole.MEMBER)
    async def on_i_done(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        member: Member = context.from_user.get_member(self.group)
        member.check_ban(BanType.INVITE, fail=True)
        t = parameters["i_select_time_id"]
        if t == "无限":
            times = float("inf")
        else:
            times = int(t)
        v = parameters["i_done_id"]
        if v == "永久":
            ttl = None
        else:
            td = parse_timedelta(v)
            ttl = int(td.total_seconds())
        digits = [s for s in string.digits if not s == "0"]
        asciis = [s for s in string.ascii_uppercase if not s == "O"]
        code = "".join(random.choices(digits + asciis, k=16))
        self.invite_codes.set(code, (member, times), ttl=ttl)
        return (
            "🔗 将该邀请链接复制给您的朋友:\n\n"
            f"`https://t.me/{self.bot.me.username}?start=_c_{code}`\n\n"
        )
    
    @operation(None)
    async def on_i_close(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        await context.message.delete()
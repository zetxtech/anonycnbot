import asyncio
from pyrogram import Client
from pyrogram.types import Message as TM

import anonyabbot

from ...model import MemberRole, Member, OperationError, BanType, Message, RedirectedMessage
from ...utils import async_partial
from .common import operation
from .worker import DeleteOperation, PinOperation, UnpinOperation


class OnCommand:
    def get_member_reply_message(self: "anonyabbot.GroupBot", message: TM):
        member: Member = message.from_user.get_member(self.group)
        rm = message.reply_to_message
        if not rm:
            raise OperationError("no message replied")
        mr: Message = Message.get_or_none(mid=rm.id, member=member)
        if not mr:
            rmr = RedirectedMessage.get_or_none(mid=rm.id, to_member=member)
            if not rmr:
                raise OperationError("message outdated")
            mr: Message = rmr.message
        return member, mr

    @operation(MemberRole.MEMBER)
    async def on_delete(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        member, mr = self.get_member_reply_message(message)
        member.cannot(BanType.MESSAGE, fail=True)
        if not mr.member.id == member.id:
            if not member.role >= MemberRole.ADMIN_BAN:
                return await info(f"⚠️ Only messages sent by you can be deleted.")
        e = asyncio.Event()
        op = DeleteOperation(member=member, finished=e, message=mr)
        await self.queue.put(op)
        msg: TM = await info(f"🔃 Message revoking from all users...", time=None)
        try:
            await asyncio.wait_for(e.wait(), 120)
        except asyncio.TimeoutError:
            await msg.edit("⚠️ Timeout to revoke this message.")
        else:
            await msg.edit(f"🗑️ Message deleted ({op.requests-op.errors}/{op.requests}).")
        await asyncio.sleep(2)
        await msg.delete()

    @operation(MemberRole.MEMBER)
    async def on_change(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        member: Member = message.from_user.get_member(self.group)
        _, mask = await self.unique_mask_pool.get_mask(member, renew=True)
        await info(f"🌈 Your mask has been changed to: {mask}")

    @operation(MemberRole.MEMBER)
    async def on_setmask(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        msg: TM = await info("⬇️ Please enter an emoji as your mask:", time=None)
        self.set_conversation(message, "sm_mask", data=msg)
        await asyncio.sleep(120)
        if await msg.delete():
            self.set_conversation(message, None)
            await info("⚠️ Timeout.", 2)

    @operation(MemberRole.ADMIN_BAN)
    async def on_ban(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)

        cmd = message.text.split(None, 1)
        try:
            _, uid = cmd
        except ValueError:
            member, mr = self.get_member_reply_message(message)
            target = mr.member
        else:
            user = await self.bot.get_users(uid)
            target = user.get_member(self.group)
            if not target:
                raise OperationError("member not found in this group")
            member: Member = message.from_user.get_member(self.group)
        if target.role >= MemberRole.ADMIN:
            member.validate(MemberRole.ADMIN_ADMIN, fail=True)
        if target.role >= MemberRole.ADMIN_ADMIN:
            member.validate(MemberRole.CREATOR, fail=True)
        if target.id == member.id:
            return await info("⚠️ Can not ban yourself.")
        if target.role >= member.role:
            return await info("⚠️ Permission denied.")
        if target.role == MemberRole.BANNED:
            return await info("⚠️ The user is already banned.")

        target.role = MemberRole.BANNED
        target.save()
        return await info("🚫 Member banned.")

    @operation(MemberRole.ADMIN_BAN)
    async def on_unban(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)

        cmd = message.text.split(None, 1)
        try:
            _, uid = cmd
        except ValueError:
            member, mr = self.get_member_reply_message(message)
            target = mr.member
        else:
            user = await self.bot.get_users(uid)
            target = user.get_member(self.group)
            if not target:
                raise OperationError("member not found in this group")
            member: Member = message.from_user.get_member(self.group)
        if target.role >= MemberRole.ADMIN:
            member.validate(MemberRole.ADMIN_ADMIN, fail=True)
        if target.role >= MemberRole.ADMIN_ADMIN:
            member.validate(MemberRole.CREATOR, fail=True)
        if target.id == member.id:
            return await info("⚠️ Can not unban yourself.")
        if target.role >= member.role:
            return await info("⚠️ Permission denied.")
        if not target.role == MemberRole.BANNED:
            return await info("⚠️ The user is not banned.")

        target.role = MemberRole.GUEST
        target.save()
        return await info("✅ Member unbanned.")

    @operation(MemberRole.ADMIN_MSG)
    async def on_pin(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        member, mr = self.get_member_reply_message(message)
        e = asyncio.Event()
        op = PinOperation(member=member, finished=e, message=mr)
        await self.queue.put(op)
        msg: TM = await info(f"🔃 Pinning message for all users...", time=None)
        try:
            await asyncio.wait_for(e.wait(), 120)
        except asyncio.TimeoutError:
            await msg.edit("⚠️ Timeout to pin this message.")
        else:
            await msg.edit(f"📌 Message pinned ({op.requests-op.errors}/{op.requests}).")
        await asyncio.sleep(2)
        await msg.delete()

    @operation(MemberRole.ADMIN_MSG)
    async def on_unpin(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        member, mr = self.get_member_reply_message(message)
        e = asyncio.Event()
        op = UnpinOperation(member=member, finished=e, message=mr)
        await self.queue.put(op)
        msg: TM = await info(f"🔃 Unpinning message for all users...", time=None)
        try:
            await asyncio.wait_for(e.wait(), 120)
        except asyncio.TimeoutError:
            await msg.edit("⚠️ Timeout to unpin this message.")
        else:
            await msg.edit(f"📌 Message unpinned ({op.requests-op.errors}/{op.requests}).")
        await asyncio.sleep(2)
        await msg.delete()

    @operation(MemberRole.ADMIN_BAN)
    async def on_reveal(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        info = async_partial(self.info, context=message)
        _, mr = self.get_member_reply_message(message)
        target: Member = mr.member
        msg = (
            f"ℹ️ Profile of this member:\n\n"
            f"Name: {target.user.name}\n"
            f"ID: {target.user.uid}\n"
            f"Role in group: {target.role.display.title()}\n"
            f"Joining date: {target.created.strftime('%Y-%m-%d')}\n"
            f"Message count: {target.n_messages}\n"
            f"Last Activity: {target.last_activity.strftime('%Y-%m-%d')}\n"
            f"Last Mask: {target.last_mask}\n\n"
            f"👁️‍🗨️ This panel is only visible to you."
        )
        await info(msg, time=15)

    @operation(MemberRole.ADMIN_BAN)
    async def on_manage(self: "anonyabbot.GroupBot", client: Client, message: TM):
        await message.delete()
        _, mr = self.get_member_reply_message(message)
        target: Member = mr.member
        return await self.to_menu_scratch("_member_detail", message.chat.id, message.from_user.id, member_id=target.id)

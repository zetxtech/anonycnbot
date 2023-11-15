import asyncio
import re

import emoji
from pyrogram import Client
from pyrogram.types import Message as TM, CallbackQuery as TC
from pyrogram.enums import MessageEntityType

import anonyabbot

from ...utils import async_partial
from ...model import Member, BanType, MemberRole, Message, PMMessage, RedirectedMessage, OperationError, User
from .common import operation
from .mask import MaskNotAvailable
from .worker import BroadcastOperation, EditOperation


class OnMessage:
    def check_message(self, message: Message, member: Member):
        member.validate(MemberRole.LEFT, fail=True, reversed=True)
        member.check_ban(BanType.MESSAGE)
        if message.media:
            member.check_ban(BanType.MEDIA)
        if message.sticker:
            member.check_ban(BanType.STICKER)
        if message.reply_markup:
            member.check_ban(BanType.MARKUP)
        if message.entities:
            for e in message.entities:
                if e.type in [
                    MessageEntityType.URL,
                    MessageEntityType.TEXT_LINK,
                    MessageEntityType.MENTION,
                    MessageEntityType.TEXT_MENTION,
                ]:
                    member.check_ban(BanType.LINK)
        content = message.text or message.caption
        if content:
            if len(content) > 200:
                member.check_ban(BanType.LONG)
            if re.search(
                r"(https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|www\.[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9]+\.[^\s]{2,}|www\.[a-zA-Z0-9]+\.[^\s]{2,})",
                content,
            ):
                member.check_ban(BanType.LINK)
        
    
    @operation(conversation=True)
    async def on_chat_instruction(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        return self.group.chat_instruction

    @operation(conversation=True)
    async def on_chat_instruction_confirm(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        conv = self.conversion.get((context.message.chat.id, context.from_user.id), None)
        if conv.status == "ci_confirm":
            event: asyncio.Event = conv.data
            event.set()
        await context.message.delete()

    @operation(req=None, conversation=True, allow_disabled=True)
    async def on_message(self: "anonyabbot.GroupBot", client: Client, message: TM):
        info = async_partial(self.info, context=message)
        
        if message.text and message.text.startswith("/"):
            message.continue_propagation()

        conv = self.conversion.get((message.chat.id, message.from_user.id), None)
        if conv:
            try:
                if conv.status == "ewmm_message":
                    if message.text:
                        if message.text == "disable":
                            content = None
                        else:
                            content = message.text
                        self.group.welcome_message = content
                        self.group.save()
                        await info(f"✅ 成功")
                    elif message.photo:
                        if message.caption == "disable":
                            content = None
                        else:
                            content = message.caption
                        self.group.welcome_message = content
                        self.group.welcome_message_photo = message.photo.file_id
                        self.group.save()
                        await info(f"✅ 成功")
                    else:
                        await info(f"⚠️ 不是有效的消息")
                elif conv.status == "ewmm_button":
                    content = message.text or message.caption
                    if not content:
                        await info(f"⚠️ 不是有效的消息")
                    else:
                        if content == "disable":
                            content = None
                        user: User = message.from_user.get_record()
                        try:
                            tm = await self.send_welcome_msg(
                                user=user,
                                msg=self.group.welcome_message,
                                button_spec=content,
                                photo=self.group.welcome_message_photo,
                            )
                            await self.to_menu_scratch(
                                "_ewmb_ok_confirm", message.chat.id, message.from_user.id, button_spec=message.text, text_message=tm.id
                            )
                        except ValueError:
                            await info(f"⚠️ 格式错误")
                elif conv.status == "eci_instruction":
                    content = message.text or message.caption
                    if not content:
                        await info(f"⚠️ 不是有效的消息")
                    else:
                        self.group.chat_instruction = message.text
                        self.group.save()
                        await info(f"✅ 成功")
                elif conv.status == "sm_mask":
                    content = message.text or message.caption
                    if not content:
                        await info(f"⚠️ 不是有效的消息")
                    else:
                        member: Member = message.from_user.get_member(self.group)
                        if not member:
                            return
                        try:
                            member.check_ban(BanType.PIN_MASK)
                            m = "".join(e["emoji"] for e in emoji.emoji_list(str(message.text)))
                            if not m:
                                raise OperationError("只有 emoji 可以作为面具")
                            if len(m) > 1:
                                member.check_ban(BanType.LONG_MASK_1)
                            if len(m) >= 3:
                                member.check_ban(BanType.LONG_MASK_2)
                            if len(m) >= 3:
                                member.check_ban(BanType.LONG_MASK_3)
                        except OperationError as e:
                            await info(f"⚠️ 抱歉, {e}.")
                            await conv.data.delete()
                        else:
                            member.pinned_mask = m
                            member.save()
                            await info(f"✅ 成功, 您将固定使用 {m} 作为面具.")
                            await conv.data.delete()
            finally:
                await message.delete()
                if isinstance(conv.context, TM):
                    await conv.context.delete()
                elif isinstance(conv.context, TC):
                    await conv.context.message.delete()
                self.set_conversation(conv.context, None)
                return
        try:
            member: Member = message.from_user.get_member(self.group)
            if not member:
                raise OperationError("您不在该群组中, 请尝试使用 /start 加入.")
            self.check_message(message, member)
        except OperationError as e:
            await info(f"⚠️ 抱歉, {e}, 此消息将被删除.", time=30)
            await message.delete()
            return


        if member.role == MemberRole.GUEST:
            if self.group.chat_instruction:
                event = asyncio.Event()
                self.set_conversation(message, "ci_confirm", event)
                imsg = await self.to_menu_scratch("_chat_instruction", chat=message.chat.id, user=message.from_user.id)
                try:
                    await asyncio.wait_for(event.wait(), timeout=120)
                except asyncio.TimeoutError:
                    await imsg.delete()
                    await message.delete()
                    return
            member.role = MemberRole.MEMBER
            member.save()

        if member.pinned_mask:
            mask = member.pinned_mask
            created = False
        else:
            try:
                created, mask = await self.unique_mask_pool.get_mask(member)
            except MaskNotAvailable:
                await info(f"⚠️ 抱歉, 目前没有可用的面具, 此消息将被删除.", time=30)
                await message.delete()
                return

        rm = message.reply_to_message
        
        if rm:
            rmm: Message = Message.get_or_none(mid=rm.id, member=member)
            if not rmm:
                rmr = RedirectedMessage.get_or_none(mid=rm.id, to_member=member)
                if rmr:
                    rmm: Message = rmr.message
                else:
                    pmm: PMMessage = PMMessage.get_or_none(redirected_mid=rm.id, to_member=member)
                    if pmm:
                        await self.pm(message)
                        return
        else:
            rmm = None
                
        m = Message.create(group=self.group, mid=message.id, member=member, mask=mask)
        member.last_mask = mask
        member.save()

        e = asyncio.Event()
        op = BroadcastOperation(context=message, member=member, finished=e, message=m, reply_to=rmm)
        
        if created:
            msg: TM = await info(f"🔃 消息正在发送, 您的面具是 {mask} ...", time=None)
        else:
            msg: TM = await info("🔃 消息正在发送 ...", time=None)
        
        await self.queue.put(op)
        try:
            await asyncio.wait_for(e.wait(), 120)
        except asyncio.TimeoutError:
            await msg.edit("⚠️ 发送消息超时.")
        else:
            await msg.edit(f"✅ 消息已发送 ({op.requests-op.errors}/{op.requests}).")
        await asyncio.sleep(2)
        await msg.delete()

    @operation(req=None, allow_disabled=True)
    async def on_unknown(self: "anonyabbot.GroupBot", client: Client, message: TM):
        info = async_partial(self.info, context=message)
        await message.delete()
        await info("⚠️ 未知命令")

    @operation(req=None, conversation=True, allow_disabled=True)
    async def on_edit_message(self: "anonyabbot.GroupBot", client: Client, message: TM):
        member: Member = message.from_user.get_member(self.group)
        if not member:
            return
        mr = Message.get_or_none(mid=message.id)
        if not mr:
            return
        e = asyncio.Event()
        op = EditOperation(context=message, member=member, finished=e, message=mr)
        await self.queue.put(op)
        try:
            await asyncio.wait_for(e.wait(), 120)
        except asyncio.TimeoutError:
            pass
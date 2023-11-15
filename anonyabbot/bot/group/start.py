import asyncio
from pyrogram import Client
from pyrogram.types import Message as TM, CallbackQuery as TC, InlineKeyboardButton, InlineKeyboardMarkup

import anonyabbot

from ...model import Member, User, MemberRole
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
                "请开始化妆舞会吧!\n\n"
                "本机器人由 [@anonycnbot](t.me/anonycnbot) 创建."
            )

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

    @operation(req=None)
    async def on_start(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TM,
        parameters: dict,
    ):
        if isinstance(context, TM):
            await context.delete()
        member: Member = context.from_user.get_member(self.group)
        user: User = context.from_user.get_record()
        if member:
            mask = member.pinned_mask or await self.unique_mask_pool.mask_for(member)
            if member.role == MemberRole.LEFT:
                member.role = MemberRole.GUEST
                member.save()
                await self.send_welcome_msg(
                    user=user,
                    msg=self.group.welcome_message,
                    button_spec=self.group.welcome_message_buttons,
                    photo=self.group.welcome_message_photo,
                )
            else:
                return (
                    "🌈 群组状态：\n\n"
                    f"成员数：{self.group.n_members}\n"
                    f"非游客成员数：{self.group._all_has_role(MemberRole.MEMBER).count()}\n\n"
                    "👤 您的成员信息：\n\n"
                    f"权限身份：{member.role.display.title()}\n"
                    f'面具：{mask if mask else "<未激活>"}\n\n'
                    f"👁️‍🗨️ 此面板仅对您可见. "
                )
        else:
            Member.create(group=self.group, user=user, role=MemberRole.GUEST)
            await self.send_welcome_msg(
                user=user,
                msg=self.group.welcome_message,
                button_spec=self.group.welcome_message_buttons,
                photo=self.group.welcome_message_photo,
            )

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
            await context.answer("⚠️ Creator of the group can not leave.")
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
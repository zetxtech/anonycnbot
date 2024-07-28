from textwrap import indent
from pyrogram import Client
from pyrogram.types import Message as TM, CallbackQuery as TC

import anonyabbot

from ...model import User, Group, UserRole
from ...config import config
from ...utils import remove_prefix, truncate_str
from ..pool import stop_group_bot
from .common import operation


class Start:
    @operation(prohibited=None)
    async def on_start(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TM,
        parameters: dict,
    ):
        if isinstance(context, TM):
            if not context.text:
                return None
            cmds = context.text.split()
            if len(cmds) == 2:
                if cmds[1] == "_createcode":
                    return await self.to_menu("create_code", context)
                if cmds[1] == "_usecode":
                    return await self.to_menu("use_code", context)
                if cmds[1].startswith("_c_"):
                    code = remove_prefix(cmds[1], "_c_")
                    return await self.to_menu("use_code", context, code=code)
                if cmds[1].startswith("_g_"):
                    gid = remove_prefix(cmds[1], "_g_")
                    return await self.to_menu("_group_detail", context, gid=gid)
        return f"🌈 欢迎 {context.from_user.name}!\n\n" "此机器人将帮助您创建一个全匿名群组. "

    @operation(prohibited=None)
    async def on_my_info(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        user: User = context.from_user.get_record()
        msg = (
            f"ℹ️ {user.name} 的个人信息:\n\n"
            f" ID: {user.uid}\n"
            f" 创建的群组数: {user.created_groups.count()}\n"
            f" 首次使用: {user.created.strftime('%Y-%m-%d')}\n"
        )
        roles = [r.display for r in user.roles()]
        if roles:
            msg += f"\n👑 角色:\n"
            for r in roles:
                msg += f"  - {r.title()}\n"
        return msg
    
    @operation()
    async def on_create_code(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        user: User = context.from_user.get_record()
        code = user.create_code(UserRole.INVITED, length = 8)
        days = config.get('father.invite_award_days', 180)
        return (
            "🔗 将以下链接复制给您的朋友:\n\n"
            f"`https://t.me/{self.bot.me.username}?start=_c_{code}`\n\n"
            f"⭐ 在您的朋友创建首个匿名群组后, 你们都将获得 {days} 天的 PRIME 特权."
        )

    @operation()
    async def on_use_code(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        if 'code' in parameters:
            user: User = context.from_user.get_record()
            used = user.use_code(parameters['code'])
            if len(used) == 1 and used[0].role == UserRole.INVITED:
                days = config.get('father.invite_award_days', 180)
                msg = (
                    f"🌈 欢迎 {context.from_user.name}!\n\n"
                    "此机器人将帮助您创建一个全匿名群组.\n"
                    f"您已被邀请并将在您创建首个匿名群组后, 获得 {days} 天 PRIME 特权.\n\n"
                    "ℹ️ 使用 /start 以开始."
                )
            elif used:
                msg = "ℹ️ 您已经获得了以下身份:\n"
                for u in used:
                    days = u.days if u.days else "permanent"
                    msg += f" {u.role.display} ({days})\n"
            else:
                msg = "⚠️ 无效邀请链接."
            return msg
        else:
            self.set_conversation(context, "use_code")
            return "❓ 输入角色码:"

    @operation()
    async def on_new_group(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        self.set_conversation(context, "ng_token")
        return (
            "🌈 您需要创建一个新的 bot 作为匿名群组:\n\n"
            "1. 通过 @botfather 创建新 bot.\n"
            "   1. 使用命令 `/newbot`\n"
            "   2. 输入群标题, 例如XX群\n"
            "   2. 输入群的用户名, 以 bot 结尾\n\n"
            "2. 将包含 **bot token** 的消息发送给我."
        )

    @operation()
    async def on_list_group(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        user: User = context.from_user.get_record()
        items = []
        g: Group
        for i, g in enumerate(user.groups(created=True)):
            item = f"{i+1} | [{truncate_str(g.title, 45)}](t.me/{g.username})"
            items.append((item, str(i + 1), g.id))
        if not items:
            await self.info("⚠️ 你没有创建群组", context=context)
            await self.to_menu("start", context)
        else:
            return items

    @operation()
    async def on_jump_group_detail(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        parameters["group_id"] = int(parameters["jump_group_detail_id"])
        await self.to_menu("_group_detail", context)

    @operation()
    async def on_group_detail(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        group: Group = Group.get_by_id(parameters["group_id"])
        msg = f"⭐ 匿名群组 [@{group.username}](t.me/{group.username}) 的信息: \n\n"
        fields = [
            f"群组名称: [{group.title}](t.me/{group.username})",
            f"创建者: {group.creator.markdown}",
            f"成员数: {group.n_members}",
            f"消息数: {group.n_messages}",
            f"已禁用: {'**是**' if group.disabled else '否'}",
            f"创建时间: {group.created.strftime('%Y-%m-%d')}",
            f"最后活动时间: {group.last_activity.strftime('%Y-%m-%d')}",
        ]
        msg += indent("\n".join(fields), "  ")
        msg += "\n\n⬇️ 请点击下面的按钮来配置群组: "
        return msg

    @operation()
    async def on_delete_group_confirm(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        group: Group = Group.get_by_id(parameters["group_id"])
        return (
            f"⚠️ 确认删除群组 [@{group.username}](t.me/{group.username})?\n"
            f"⚠️ 此群组有 {group.n_members} 个成员和 {group.n_messages} 条消息. \n"
            f'⚠️ 此群组于 {group.created.strftime("%Y-%m-%d")} 创建. '
        )

    @operation()
    async def on_delete_group(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        group: Group = Group.get_by_id(parameters["group_id"])
        await stop_group_bot(group.token)
        group.disabled = True
        group.save()
        await context.answer("✅ 群组已删除")
        await self.to_menu("list_group", context)

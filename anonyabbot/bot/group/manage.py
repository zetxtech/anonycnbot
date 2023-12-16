import asyncio
from datetime import datetime
from textwrap import indent
from pyrogram import Client
from pyrogram.types import CallbackQuery as TC
from pyrubrum import Element

import anonyabbot

from ...utils import truncate_str, parse_timedelta
from ...model import Member, db, MemberRole, BanType, BanGroup
from .common import operation


class Manage:
    @operation(MemberRole.ADMIN)
    async def on_group_details(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        return (
            f"👑 欢迎群管理员 {context.from_user.name}!\n\n"
            "👁️‍🗨️ 这个面板仅对您可见\n"
            "⬇️ 请点击下面的按钮来配置群组: "
        )

    @operation(MemberRole.ADMIN)
    async def on_group_info(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        group = self.group
        member: Member = context.from_user.get_member(self.group)
        creator = group.creator.markdown if member.role >= MemberRole.ADMIN_BAN else group.creator.masked_name
        waiting_delay = f"{self.worker_status['time'] / self.worker_status['requests']:.1f} 秒" if self.worker_status['requests'] else "无数据"
        msg = f"ℹ️ 群组信息: \n\n"
        fields = [
            f"群名称: [{group.title}](t.me/{group.username})",
            f"创建者: {creator}",
            f"成员数: {group.n_members}",
            f"消息数: {group.n_messages}",
            f"平均传播延迟: {waiting_delay}",
            f"禁用: {'**是**' if group.disabled else '否'}",
            f"创建时间: {group.created.strftime('%Y-%m-%d')}",
            f"最后活动时间: {group.last_activity.strftime('%Y-%m-%d')}",
        ]
        msg += indent("\n".join(fields), "  ")
        return msg

    @operation(MemberRole.ADMIN_BAN)
    async def on_edit_default_ban_group(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        if parameters["menu_id"] == 'edbg_select':
            current_selection = parameters.get("edbg_current", None)
        else:
            current_selection = None
        if not current_selection:
            parameters["edbg_current"] = current_selection = [t.value for t in self.group.default_bans()]

        items = []
        types = [t for t in BanType if not t == BanType.NONE]
        for i, t in enumerate(types):
            item = f"{i+1:<2} | {t.display}"
            if t.value in current_selection:
                item = f"`   {item}`"
            else:
                item = f"` ✓ {item}`"
            items.append((item, str(i + 1), t.value))
        return items

    @operation(MemberRole.ADMIN_BAN)
    async def on_edbg_select(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        selected = parameters.get("edbg_select_id", None)
        if selected:
            if "edbg_current" in parameters:
                if selected in parameters["edbg_current"]:
                    parameters["edbg_current"].remove(selected)
                else:
                    parameters["edbg_current"].append(selected)
            else:
                parameters["edbg_current"] = [selected]
        await self.to_menu("edit_default_ban_group", context=context)

    @operation(MemberRole.ADMIN_BAN)
    async def on_edbg_done(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        current_selection = parameters.get("edbg_current", [])
        types = [BanType(v) for v in current_selection]
        with db.atomic():
            original = self.group.default_ban_group
            self.group.default_ban_group = BanGroup.generate(types)
            self.group.save()
            original.delete_instance()
        await context.answer("✅ 成功")
        await self.to_menu("_group_details", context)

    @operation(MemberRole.ADMIN_MSG)
    async def on_edit_welcome_message(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        if self.group.welcome_message:
            msg = f"🧾 群组欢迎消息已设置为: \n\n{self.group.welcome_message}"
        else:
            msg = f"🧾 群组欢迎消息为空"
        if self.group.welcome_message_photo:
            msg += f"\n\n🖼️ 群组欢迎消息头图已设置"
        if self.group.welcome_message_buttons:
            msg += f"\n\n⌨️ 群组欢迎消息按钮已设置"
        msg += "\n\n⬇️ 请点击下面的按钮进行配置: "
        return msg

    @operation(MemberRole.ADMIN_MSG)
    async def on_edit_welcome_message_message(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        self.set_conversation(context, "ewmm_message")
        return (
            "⬇️ 输入新的欢迎消息 (仅对新用户自己可见, 可以包含图片): \n\n"
            "ℹ️ 你可以用以下方法表示变量：\n"
            "`  {name}       : 用户名`\n"
            "`  {masked_name}: 加马赛克的用户名`\n"
            "`  {markdown}   : 用户名并带有链接`\n\n"
            "ℹ️ 输入 `disable` 以禁用欢迎消息"
        )

    @operation(MemberRole.ADMIN_MSG)
    async def on_edit_welcome_message_button(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        self.set_conversation(context, "ewmm_button")
        return (
            "⬇️ 定义新的欢迎消息按钮：\n\n"
            "ℹ️ 按钮应该以以下格式定义：\n\n"
            "`按钮1: https://button1.url | 按钮2: https://button2.url`\n\n"
            "1. 每行都是一个按钮\n"
            "2. 使用 t.me/username 以链接到用户 / 群组"
        )
    
    @operation(MemberRole.ADMIN_MSG)
    async def button_toggle_latest_message(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        status = parameters.get("show_latest_message", self.group.welcome_latest_messages)
        return ("✅" if status else "") + " 入群推送最新消息"
    
    @operation(MemberRole.ADMIN_MSG)
    async def on_toggle_latest_message(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        status = not parameters.get("show_latest_message", True)
        parameters["show_latest_message"] = status
        self.group.welcome_latest_messages = status
        self.group.save()
        await context.answer('✅ 成功')
        await self.to_menu('edit_welcome_message', context)

    @operation(MemberRole.ADMIN_MSG)
    async def on_ewmb_ok(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        button_spec = parameters["button_spec"]
        test_message_id = parameters["text_message"]
        self.group.welcome_message_buttons = button_spec
        self.group.save()
        await self.bot.delete_messages(self.group.username, test_message_id)
        m = await self.bot.send_message(context.message.chat.id, "✅ 成功")
        await asyncio.sleep(5)
        await m.delete()
        await context.message.delete()


    @operation(MemberRole.ADMIN_MSG)
    async def on_edit_chat_instruction(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        self.set_conversation(context, "eci_instruction")
        if self.group.chat_instruction:
            msg = f"🧾 聊天指南已设置为：\n\n{self.group.chat_instruction}\n\n"
        else:
            msg = f"🧾 聊天指南未设置\n\n"
        msg += (
            "ℹ️ 聊天指南是在用户发送任何匿名消息之前需要同意的提示。\n\n"
            "ℹ️ 示例："
            "```示例\n"
            "⭐ 在你发送第一条匿名消息之前，请阅读以下内容：\n\n"
            "1. 您发送的消息将以匿名形式广播给其他成员。\n"
            "2. 请勿直接使用 Telegram 的菜单删除消息，请使用 `/delete` 删除回复的消息。\n"
            "3. 如果你编辑了一条消息，该编辑也将将会广播给其他成员。\n"
            "4. 请享受聊天的乐趣！```\n\n"
            "⬇️ 输入新的聊天指南（只对你可见）：\n"
            "ℹ️ （输入 `disable` 以禁用聊天指南）"
        )
        return msg

    @operation(MemberRole.ADMIN_BAN)
    async def on_list_group_members(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        sorting, desc = parameters.get("lgm_sorting", ("role", True))
        members = self.group.members.where(Member.role >= MemberRole.GUEST)
        if sorting == "role":
            if desc:
                members = members.order_by(Member.role.desc())
            else:
                members = members.order_by(Member.role)
        else:
            if desc:
                members = members.order_by(Member.last_activity.desc())
            else:
                members = members.order_by(Member.last_activity)
        items = []
        m: Member
        for i, m in enumerate(members.iterator()):
            item = f"{i+1} | [{truncate_str(m.user.name, 20)}](t.me/{m.user.username})"
            items.append((item, str(i + 1), m.id))
        return items

    @operation(MemberRole.ADMIN_BAN)
    async def button_lgm_switch_activity(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        sorting, desc = parameters.get("lgm_sorting", ("role", True))
        if sorting == "activity":
            return "🔽 最近活跃" if desc else "🔼 最近活跃"
        else:
            return "↔ 最近活跃"

    @operation(MemberRole.ADMIN_BAN)
    async def on_lgm_switch_activity(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        sorting, desc = parameters.get("lgm_sorting", ("role", True))
        if sorting == "activity":
            parameters["lgm_sorting"] = ("activity", not desc)
            await context.answer("🔼 最旧到最新" if desc else "🔽 最新到最旧")
        else:
            parameters["lgm_sorting"] = ("activity", True)
            await context.answer("🔽 最新到最旧")
        await self.to_menu("list_group_members", context)

    @operation(MemberRole.ADMIN_BAN)
    async def button_lgm_switch_role(
        self: "anonyabbot.FatherBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        sorting, desc = parameters.get("lgm_sorting", ("role", True))
        if sorting == "role":
            return "🔽 权限角色" if desc else "🔼 权限角色"
        else:
            return "↔ 权限角色"

    @operation(MemberRole.ADMIN_BAN)
    async def on_lgm_switch_role(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        sorting, desc = parameters.get("lgm_sorting", ("role", True))
        if sorting == "role":
            parameters["lgm_sorting"] = ("role", not desc)
            await context.answer("🔼 权限由低到高" if desc else "🔽 权限由高到低")
        else:
            parameters["lgm_sorting"] = ("role", True)
            await context.answer("🔽 权限由高到低")
        await self.to_menu("list_group_members", context)

    @operation(MemberRole.ADMIN_BAN)
    async def on_jump_member_detail(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        parameters["member_id"] = int(parameters["jump_member_detail_id"])
        await self.to_menu("_member_detail", context)

    @operation(MemberRole.ADMIN_BAN)
    async def on_member_detail(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        target: Member = Member.get_by_id(parameters["member_id"])
        return (
            f"👤 {target.user.markdown} 的详细信息：\n\n"
            f"ID: {target.user.uid}\n"
            f"群组中的权限角色：{target.role.display.title()}\n"
            f"加入日期：{target.created.strftime('%Y-%m-%d')}\n"
            f"消息数：{target.n_messages}\n"
            f"最后活动时间：{target.last_activity.strftime('%Y-%m-%d')}\n"
            f"最后一次发信使用的面具：{target.last_mask}\n\n"
            f"👁️‍🗨️ 此面板仅对您可见"
        )

    @operation(MemberRole.ADMIN_BAN)
    async def items_edit_member_role_select(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        items = []
        for r in MemberRole:
            button = r.name
            items.append(Element(button, r.value))
        return items

    @operation(MemberRole.ADMIN_BAN)
    async def on_edit_member_role(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        role = MemberRole(int(parameters["edit_member_role_id"]))
        target: Member = Member.get_by_id(parameters["member_id"])
        member: Member = context.from_user.get_member(self.group)
        if target.role >= MemberRole.ADMIN or role >= MemberRole.ADMIN:
            member.validate(MemberRole.ADMIN_ADMIN, fail=True)
        if target.role >= MemberRole.ADMIN_ADMIN:
            member.validate(MemberRole.CREATOR, fail=True)
        if target.id == member.id:
            await context.answer("⚠️ 无法编辑自己")
            await self.to_menu("_member_detail", context)
        if target.role >= member.role:
            await context.answer("⚠️ 无法编辑权限高于您的成员")
            await self.to_menu("_member_detail", context)
        target.role = role
        target.save()
        await context.answer("✅ 修改成功")
        await self.to_menu("_member_detail", context)

    @operation(MemberRole.ADMIN_BAN)
    async def header_edit_member_ban_group(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        target: Member = Member.get_by_id(parameters["member_id"])
        return f"👤 Set permission for {target.user.markdown}:\n"

    @operation(MemberRole.ADMIN_BAN)
    async def on_edit_member_ban_group(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        target: Member = Member.get_by_id(parameters["member_id"])
        
        if parameters["menu_id"] == 'embg_select':
            current_selection = parameters.get("embg_current", None)
        else:
            current_selection = None
        if not current_selection:
            if target.ban_group:
                parameters["embg_current"] = current_selection = [t.type.value for t in target.ban_group.entries.iterator()]
            else:
                parameters["embg_current"] = current_selection = [t.value for t in self.group.default_bans()]

        items = []
        types = [t for t in BanType if not t == BanType.NONE]
        for i, t in enumerate(types):
            item = f"{i+1:<2} | {t.display}"
            if t.value in current_selection:
                item = f"`   {item}`"
            else:
                item = f"` ✓ {item}`"
            items.append((item, str(i + 1), t.value))
        return items

    @operation(MemberRole.ADMIN_BAN)
    async def on_embg_select(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        selected = parameters.get("embg_select_id", None)
        if selected:
            if "embg_current" in parameters:
                if selected in parameters["embg_current"]:
                    parameters["embg_current"].remove(selected)
                else:
                    parameters["embg_current"].append(selected)
            else:
                parameters["embg_current"] = [selected]
        await self.to_menu("edit_member_ban_group", context=context)

    @operation(MemberRole.ADMIN_BAN)
    async def items_edit_member_ban_group_select_time(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        return [Element(i, i) for i in ["1m", "10m", "1h", "12h", "1d", "3d", "5d", "10d", "30d", "180d", "1y", "10y"]]

    @operation(MemberRole.ADMIN_BAN)
    async def on_embg_done(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        target: Member = Member.get_by_id(parameters["member_id"])
        member: Member = context.from_user.get_member(self.group)
        if target.role >= MemberRole.ADMIN:
            member.validate(MemberRole.ADMIN_ADMIN, fail=True)
        if target.role >= MemberRole.ADMIN_ADMIN:
            member.validate(MemberRole.CREATOR, fail=True)
        if target.id == member.id:
            await context.answer("⚠️ 无法编辑自己")
            await self.to_menu("_member_detail", context)
        if target.role >= member.role:
            await context.answer("⚠️ 无法编辑权限高于您的成员")
            await self.to_menu("_member_detail", context)

        current_selection = parameters.get("embg_current", [])
        td_str = parameters["embg_done_id"]
        td = parse_timedelta(td_str)
        until = datetime.now() + td
        types = [BanType(v) for v in current_selection]
        with db.atomic():
            original = target.ban_group
            target.ban_group = BanGroup.generate(types, until=until)
            target.save()
            if original:
                original.delete_instance()
        await context.answer("✅ 修改成功")
        await self.to_menu("_member_detail", context)

    @operation(MemberRole.ADMIN_BAN)
    async def on_kick_member_confirm(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        target: Member = Member.get_by_id(parameters["member_id"])
        return (
            f"⚠️ 确定要踢除成员 {target.user.markdown} 吗? \n"
            f"⚠️ 该成员的角色是 {target.role.display} . \n"
            f"⚠️ 该成员已发送 {target.n_messages} 条消息. "
        )

    @operation(MemberRole.ADMIN_BAN)
    async def on_kick_member(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        target: Member = Member.get_by_id(parameters["member_id"])
        member: Member = context.from_user.get_member(self.group)
        if target.role >= MemberRole.ADMIN:
            member.validate(MemberRole.ADMIN_ADMIN, fail=True)
        if target.role >= MemberRole.ADMIN_ADMIN:
            member.validate(MemberRole.CREATOR, fail=True)
        if target.id == member.id:
            await context.answer("⚠️ 无法编辑自己")
            await self.to_menu("_member_detail", context)
        if target.role >= member.role:
            await context.answer("⚠️ 无法编辑权限高于您的成员")
            await self.to_menu("_member_detail", context)
        target.role = MemberRole.BANNED
        target.save()
        await context.answer("✅ 编辑成功")
        await self.to_menu("list_group_members", context)

    @operation(MemberRole.ADMIN)
    async def on_close_group_details(
        self: "anonyabbot.GroupBot",
        handler,
        client: Client,
        context: TC,
        parameters: dict,
    ):
        await context.message.delete()
        await context.answer()

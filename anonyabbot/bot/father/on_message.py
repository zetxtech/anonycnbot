import asyncio
import re
from pyrogram import Client
from pyrogram.types import Message as TM
from pyrogram.errors import RPCError

import anonyabbot

from ...utils import async_partial
from ...model import User, Group
from ..pool import start_group_bot
from .common import operation


class OnMessage:
    @operation(prohibited=None, conversation=True)
    async def on_messagge(
        self: "anonyabbot.FatherBot",
        client: Client,
        message: TM,
    ):
        info = async_partial(self.info, context=message, time=None)
        conv = self.conversion.get((message.chat.id, message.from_user.id), None)
        user: User = message.from_user.get_record()
        if not conv:
            message.continue_propagation()
        try:
            if message.text:
                if message.text.startswith("/"):
                    message.continue_propagation()
                if conv.status == "use_code":
                    used = user.use_code(message.text)
                    if used:
                        msg = "ℹ️ 你已成为以下角色:\n"
                        for u in used:
                            days = u.days if u.days else "永久"
                            msg += f" {u.role.display} ({days})\n"
                    else:
                        msg = "⚠️ 无效的角色码"
                    return await info(msg)
                if conv.status == "ng_token":
                    match = re.search(r"[0-9]{8,10}:[a-zA-Z0-9_-]{35}", message.text)
                    if not match:
                        return await info("⚠️ 无效的 bot 令牌")
                    token = match.group(0)
                    group = Group.get_or_none(token=token)
                    if group:
                        if group.disabled:
                            msg = (
                                "⚠️ 该群组已被删除. \n\n"
                                "如果您想重新创建它, 请从 [@botfather](t.me/botfather) 获取新的机器人令牌. \n"
                                "如果您想恢复它, 请联系系统管理员. \n"
                            )
                            return await info(msg)
                        else:
                            return await info("⚠️ 该机器人已经是匿名群组. ")
                    msg = await info("ℹ️ 请稍等, 群组正在启动...")
                    try:
                        groupbot = await start_group_bot(token, creator=user)
                    except asyncio.TimeoutError:
                        await msg.delete()
                        return await info("⚠️ 启动群组机器人超时, 请稍后重试. ")
                    except RPCError as e:
                        await msg.delete()
                        return await info(f"⚠️ 启动群组机器人失败: \n{e.MESSAGE.format(value=e.value)}. ")
                    else:
                        await msg.delete()
                        return await info(
                            f"✅ 成功. 现在您可以访问匿名群组 [@{groupbot.group.username}](t.me/{groupbot.group.username}) 了. "
                        )
        finally:
            self.set_conversation(conv.context, None)

        message.continue_propagation()

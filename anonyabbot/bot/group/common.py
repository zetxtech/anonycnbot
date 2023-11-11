from typing import Union

from loguru import logger
from pyrogram import ContinuePropagation, Client
from pyrogram.types import Message as TM, CallbackQuery as TC
from pyrogram.errors import UserDeactivated, MessageNotModified

import anonyabbot

from ...model import OperationError, MemberRole, Member


def operation(req: MemberRole = MemberRole.GUEST, conversation=False, allow_disabled=False, touch=True):
    def deco(func):
        async def wrapper(*args, **kw):
            try:
                self: "anonyabbot.GroupBot"
                context: Union[TM, TC]
                client: Client
                if len(args) == 5:
                    self, handler, client, context, parameters = args  # from menu
                elif len(args) == 3:
                    self, client, context = args  # from message
                else:
                    raise ValueError("wrong number of arguments")
                try:
                    if touch:
                        await self.touch()
                    if not conversation:
                        self.set_conversation(context, status=None)
                    if (not allow_disabled) and self.group.disabled:
                        raise OperationError("this group has been deleted and cannot be operated")
                    if req:
                        member: Member = context.from_user.get_member(self.group)
                        if not member:
                            raise OperationError("you are not in this group")
                        member.validate(req, fail=True)
                        member.touch()
                    return await func(*args, **kw)
                except ContinuePropagation:
                    raise
                except OperationError as e:
                    await self.info(f"⚠️ Fail: {e}.", context, alert=True)
                except MessageNotModified:
                    pass
                except Exception as e:
                    if isinstance(e, ContinuePropagation):
                        raise
                    logger.opt(exception=e).warning("Callback error:")
                    await self.info(f"⚠️ Error occured.", context, alert=True)
                    return
            except UserDeactivated as e:
                if self.group:
                    self.group.disabled = True
                    self.group.save()
                self.failed.set()
                logger.info(f'Group @{client.me.username} disabled because token deactivated.')
        return wrapper

    return deco

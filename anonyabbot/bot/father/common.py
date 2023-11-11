from typing import Union

from loguru import logger
from pyrogram import ContinuePropagation
from pyrogram.types import Message as TM, CallbackQuery as TC

import anonyabbot

from ...model import OperationError, UserRole, User


def operation(req: UserRole = None, prohibited: UserRole = UserRole.BANNED, conversation=False):
    def deco(func):
        async def wrapper(*args, **kw):
            self: "anonyabbot.FatherBot"
            context: Union[TM, TC]
            if len(args) == 5:
                self, handler, client, context, parameters = args  # from menu
            elif len(args) == 3:
                self, client, context = args  # from message
            else:
                raise ValueError("wrong number of arguments")
            try:
                if not conversation:
                    self.set_conversation(context, status=None)
                user: User = context.from_user.get_record()
                if req:
                    user.validate(req, fail=True)
                if prohibited:
                    user.validate(prohibited, fail=True, reversed=True)
                return await func(*args, **kw)
            except ContinuePropagation:
                raise
            except OperationError as e:
                await self.info(f"⚠️ Fail: {e}.", context, alert=True)
            except Exception as e:
                if isinstance(e, ContinuePropagation):
                    raise
                logger.opt(exception=e).warning("Callback error:")
                await self.info(f"⚠️ Error occured.", context=context, alert=True)
                return False

        return wrapper

    return deco

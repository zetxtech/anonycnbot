from loguru import logger
from pyrogram.types import User as TU

from ..model import db, User, Group, UserRole


def patch_pyrogram():
    def name(self: TU):
        naming = (self.first_name, self.last_name)
        if not any(naming):
            return "<Deleted Account>"
        else:
            return " ".join([n for n in naming if n])

    def get_record(self: TU, create=True):
        ur: User = User.get_or_none(uid=self.id)
        if not ur:
            if create:
                with db.atomic():
                    ur = User.create(uid=self.id)
                    logger.trace(f"New user: {self.name}.")
                    if User.select().count() == 1:
                        ur.add_role([UserRole.CREATOR, UserRole.ADMIN])
                        ur.save()
                        logger.warning(f"First user is set as super admin: {self.name}.")
            else:
                return None
        if ur:
            ur.username = self.username
            ur.firstname = self.first_name
            ur.lastname = self.last_name
            ur.save()
            return ur

    def get_member(self: TU, group: Group):
        user: User = self.get_record()
        return user.member_in(group)

    setattr(TU, "name", property(name))
    setattr(TU, "get_record", get_record)
    setattr(TU, "get_member", get_member)

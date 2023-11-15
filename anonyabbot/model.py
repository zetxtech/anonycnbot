from __future__ import annotations

from datetime import datetime
import random
import string
from typing import Iterable, List, Type, Union

from aenum import IntEnum
from peewee import *

from .utils import to_iterable, extract

db = SqliteDatabase(None)


class OperationError(Exception):
    pass


class UserRoleError(OperationError):
    def __init__(self, roles: Iterable[UserRole], reversed=False):
        displays = [r.display for r in to_iterable(roles)]
        if not reversed:
            if len(displays) == 1:
                super().__init__(f"您不是{displays[0]}")
            else:
                super().__init__(f'您不是{"或".join(displays)}')
        else:
            if len(displays) == 1:
                super().__init__(f"您是{displays[0]}")
            else:
                super().__init__(f'您是{"或".join(displays)}')


class MemberRoleError(OperationError):
    def __init__(self, role: MemberRole, reversed=False):
        if not reversed:
            super().__init__(f"您不是该群组的{role.display}")
        else:
            super().__init__(f"您是该群组{role.display}")


class BanError(OperationError):
    def __init__(self, type: BanType, member=True, until: datetime = None):
        until_spec = f', 直到 `{until.strftime("%Y-%m-%d %H:%M")}`' if until else ""
        super().__init__(f"{'你不能' if member else '所有人都不能'}在该群组中{type.display}{until_spec}")


class UserRole(IntEnum):
    _init_ = "value display"

    NONE = 0, "未知用户"
    BANNED = 10, "被封禁用户"
    GROUPER = 20, "群组创建者用户"
    AWARDED = 30, "荣誉用户"
    PAYING = 40, "付费用户"
    ADMIN = 90, "系统管理员"
    CREATOR = 100, "系统创建者"


class MemberRole(IntEnum):
    _init_ = "value display"

    NONE = 0, "未知用户"
    BANNED = 10, "封禁用户"
    LEFT = 20, "退群用户"
    GUEST = 30, "游客"
    MEMBER = 40, "成员"
    ADMIN = 60, "管理员"
    ADMIN_MSG = 70, "可以置顶消息的管理员"
    ADMIN_BAN = 80, "可以封禁其他用户的管理员"
    ADMIN_ADMIN = 90, "可以设置管理员的管理员"
    CREATOR = 100, "创建者"


class BanType(IntEnum):
    _init_ = "value display"

    NONE = 0, "未知"
    RECEIVE = 10, "接收消息"
    MESSAGE = 20, "发送消息"
    MEDIA = 21, "发送带有媒体的消息"
    STICKER = 22, "发送贴纸"
    MARKUP = 23, "发送带有按钮的消息"
    LONG = 24, "发送长度超过 200 个字符的消息"
    LINK = 25, "发送包含链接的消息"
    PIN_MASK = 30, "设定面具"
    LONG_MASK_1 = 40, "设定超过 1 个 emoji 的面具"
    LONG_MASK_2 = 41, "设定超过 2 个 emoji 的面具"
    LONG_MASK_3 = 42, "设定超过 3 个 emoji 的面具"
    PM_USER = 50, "私聊其他用户"
    PM_ADMIN = 51, "私聊管理员"


class EnumField(IntegerField):
    def __init__(self, choices: Type[IntEnum], *args, **kw):
        super(IntegerField, self).__init__(*args, **kw)
        self.choices = choices

    def db_value(self, value: IntEnum):
        return value.value

    def python_value(self, value: int):
        return self.choices(value)


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    id = AutoField()
    uid = IntegerField(unique=True)
    username = CharField(index=True, null=True)
    firstname = CharField(index=True, null=True)
    lastname = CharField(index=True, null=True)
    created = DateTimeField(default=datetime.now)

    @property
    def name(self):
        return " ".join([n for n in (self.firstname, self.lastname) if n])

    @property
    def markdown(self):
        return f"[{self.name}](tg://user?id={self.uid})"

    @property
    def masked_name(self):
        ufn = self.firstname
        uln = self.lastname
        if ufn and uln:
            if len(ufn) == 1:
                return "◼" * 2 + uln[-1]
            elif len(uln) == 1:
                return ufn[0] + "◼" * 2
            else:
                return ufn[0] + "◼ ◼" + uln[-1]
        elif ufn:
            return ufn[0] + "◼" * 2
        elif uln:
            return "◼" * 2 + uln[-1]
        else:
            return "◼" * 2

    @property
    def is_banned(self):
        return self.validate(UserRole.BANNED)

    def roles(self):
        for r in UserRole:
            if self.validate(r):
                yield r

    @classmethod
    def _all_in_role(cls, roles: Iterable[UserRole]):
        return (
            cls.select()
            .join(Validation)
            .where(Validation.role << to_iterable(roles), (Validation.until > datetime.now()) | (Validation.until.is_null()))
        )

    @classmethod
    def all_in_role(cls, roles: Iterable[UserRole]):
        for u in cls._all_in_role(roles).iterator():
            yield u

    @classmethod
    def n_in_role(cls, roles: Iterable[UserRole]):
        return cls._all_in_role(roles).count()

    def validate(self, roles: Iterable[UserRole], fail=False, reversed=False):
        if self._validation_for(roles).count():
            result = not reversed
        else:
            result = reversed

        if fail and not result:
            raise UserRoleError(roles, reversed=reversed)
        return result

    def _validation_for(self, roles: Iterable[UserRole] = None):
        if roles is not None:
            return self.validations.where(
                Validation.role << to_iterable(roles), (Validation.until > datetime.now()) | (Validation.until.is_null())
            )
        else:
            return self.validations.where((Validation.until > datetime.now()) | (Validation.until.is_null()))

    def add_validation(
        self,
        roles: Iterable[UserRole],
        days: int = 0,
        from_request: ValidationRequest = None,
    ):
        with db.atomic():
            for role in to_iterable(roles):
                validation: Validation = self._validation_for(role).get_or_none()
                if not validation:
                    if days is None:
                        until = None
                    else:
                        until = datetime.now() + datetime.timedelta(days=days)
                    validation = Validation(user=self, role=role, until=until)
                else:
                    if days is None:
                        validation.until = None
                    else:
                        validation.until += datetime.timedelta(days=days)
                validation.save()
                if from_request:
                    from_request.used = validation
                    from_request.save()

    def remove_validation(self, roles: Iterable[UserRole] = None):
        count = 0
        with db.atomic():
            v: Validation
            for v in self._validation_for(roles).iterator():
                v.until = datetime.now()
                v.save()
                count += 1
        return count

    def create_code(
        self,
        roles: Iterable[UserRole],
        days: int = None,
        length: int = 16,
        num: int = 1,
    ) -> Union[List[str], str]:
        codes = []
        with db.atomic():
            for _ in range(num):
                digits = [s for s in string.digits if not s == "0"]
                asciis = [s for s in string.ascii_uppercase if not s == "O"]
                code = "".join(random.choices(digits + asciis, k=length))
                for r in to_iterable(roles):
                    ValidationRequest.create(code=code, role=r, days=days, created_by=self)
                codes.append(code)
        return extract(codes)

    def create_request(self, roles: Iterable[UserRole], days: int = None) -> Union[List[ValidationRequest], ValidationRequest]:
        requests = []
        with db.atomic():
            for r in to_iterable(roles):
                vr = ValidationRequest.create(code=None, role=r, days=days, created_by=self)
                requests.append(vr)
        return extract(requests)

    def add_role(self, roles: Iterable[UserRole], days: int = None):
        with db.atomic():
            for r in to_iterable(roles):
                request = self.create_request(r, days=days)
                self.add_validation(r, days=days, from_request=request)

    def use_code(self, code: str) -> List[ValidationRequest]:
        used = []
        with db.atomic():
            vcs = ValidationRequest.select().where(ValidationRequest.code == code, ~(ValidationRequest.used))
            vc: ValidationRequest
            for vc in vcs.iterator():
                if vc.code == code and not vc.used:
                    self.add_validation(vc.role, days=vc.days, from_request=vc)
                    used.append(vc)
        return used

    def member_in(self, group: Group):
        return self.member_profiles.join(Group).where(Group.id == group.id).get_or_none()

    def groups(self, allow_disabled=False, created=False):
        mp: Member
        if created:
            if allow_disabled:
                for g in self.created_groups.iterator():
                    yield g
            else:
                for g in self.created_groups.where(~(Group.disabled)).iterator():
                    yield g
        else:
            if allow_disabled:
                for mp in self.member_profiles.where(Member.role >= MemberRole.GUEST).iterator():
                    yield mp.group
            else:
                for mp in self.member_profiles.where(Member.role >= MemberRole.GUEST).join(Group).where(~(Group.disabled)).iterator():
                    yield mp.group


class Validation(BaseModel):
    id = AutoField()
    user = ForeignKeyField(User, backref="validations")
    role = EnumField(UserRole, default=UserRole.NONE)
    until = DateTimeField(default=datetime.now, null=True)
    created = DateTimeField(default=datetime.now)

    @property
    def by(self):
        results = set()
        r: ValidationRequest
        for r in self.requests.iterator():
            results.add(r.created_by)
        return results


class ValidationRequest(BaseModel):
    id = AutoField()
    code = CharField(null=True)
    role = EnumField(UserRole, default=UserRole.NONE)
    days = IntegerField(null=True)
    created = DateTimeField(default=datetime.now)
    created_by = ForeignKeyField(User, backref="validation_requests")
    used = ForeignKeyField(Validation, backref="requests", null=True, default=None)


class BanGroup(BaseModel):
    id = AutoField()
    created = DateTimeField(default=datetime.now)
    until = DateTimeField(default=datetime.now, null=True)

    default_types = []

    @classmethod
    def generate(cls, types: List[BanType] = None, until: datetime = None):
        if types is None:
            types = cls.default_types
        with db.atomic():
            group = cls.create(until=until)
            for t in to_iterable(types):
                BanGroupEntry.create(type=t, group=group)
        return group


class BanGroupEntry(BaseModel):
    id = AutoField()
    type = EnumField(BanType, default=BanType.NONE)
    group = ForeignKeyField(BanGroup, backref="entries")


class Group(BaseModel):
    id = AutoField()
    uid = IntegerField(index=True)
    token = CharField(max_length=50, unique=True)
    username = CharField(index=True)
    title = CharField(index=True, null=True)
    creator = ForeignKeyField(User, backref="created_groups")
    created = DateTimeField(default=datetime.now)
    last_activity = DateTimeField(default=datetime.now)
    default_ban_group = ForeignKeyField(BanGroup, backref="linked_groups")
    welcome_message = TextField(null=True, default=None)
    welcome_message_photo = TextField(null=True, default=None)
    welcome_message_buttons = TextField(null=True, default=None)
    chat_instruction = TextField(null=True, default=None)
    disabled = BooleanField(default=False)

    @property
    def n_members(self):
        return self.members.where(Member.role >= MemberRole.GUEST).count()

    @property
    def n_messages(self):
        return self.messages.count()

    def default_bans(self):
        e: BanType
        for e in self.default_ban_group.entries.iterator():
            yield e.type

    def _all_has_role(self, role: MemberRole):
        return self.members.where(Member.role >= role, Member.role >= MemberRole.GUEST)

    def all_has_role(self, roles: MemberRole):
        for u in self._all_has_role(roles).iterator():
            yield u

    def user_members(self, users: List[User] = None):
        if users is None:
            m: Member
            for m in self.members.where(Member.role >= MemberRole.GUEST).iterator():
                yield m
        else:
            user_ids = [u.id for u in to_iterable(users)]
            m: Member
            for m in self.members.where(Member.role >= MemberRole.GUEST).join(User).where(User.id << user_ids).iterator():
                yield m

    def member_messages(self, members: List[Member] = None):
        if members is None:
            for m in self.messages.iterator():
                yield m
        else:
            member_ids = [m.id for m in to_iterable(members)]
            m: Message
            for m in self.messages.join(Member).where(Member.id << member_ids).iterator():
                yield m

    def touch(self):
        self.last_activity = datetime.now()
        self.save()

    def cannot(self, ban: BanType, fail=False):
        group_scope: BanGroupEntry = self.default_ban_group.entries.where(BanGroupEntry.type == ban).get_or_none()
        if group_scope:
            if fail:
                raise BanError(type=ban, member=False, until=self.default_ban_group.until)
            return True
        return False


class Member(BaseModel):
    id = AutoField()
    group = ForeignKeyField(Group, backref="members")
    user = ForeignKeyField(User, backref="member_profiles")
    role = EnumField(MemberRole, default=MemberRole.GUEST)
    created = DateTimeField(default=datetime.now)
    last_activity = DateTimeField(default=datetime.now)
    last_mask = CharField(null=True, default=None)
    pinned_mask = CharField(null=True, default=None)
    ban_group = ForeignKeyField(BanGroup, backref="linked_members", null=True)

    @property
    def is_banned(self):
        return not self.validate(MemberRole.BANNED, reversed=True)

    @property
    def n_messages(self):
        return self.messages.count()

    def touch(self):
        self.last_activity = datetime.now()
        self.save()

    def validate(self, role: MemberRole, fail=False, reversed=False):
        if not reversed:
            if self.role >= role:
                return True
            else:
                if fail:
                    raise MemberRoleError(role, reversed=False)
                return False
        else:
            if self.role <= role:
                if fail:
                    raise MemberRoleError(role, reversed=True)
                return False
            else:
                return True

    def check_ban(self, ban: BanType, fail=True, check_group=True):
        if self.validate(MemberRole.ADMIN):
            return False
        if self.ban_group:
            member_scope: BanGroupEntry = self.ban_group.entries.where(BanGroupEntry.type == ban).get_or_none()
            if member_scope:
                if fail:
                    raise BanError(type=ban, member=True, until=self.ban_group.until)
                return True
        if check_group:
            group_scope: BanGroupEntry = self.group.default_ban_group.entries.where(BanGroupEntry.type == ban).get_or_none()
            if group_scope:
                if fail:
                    raise BanError(type=ban, member=False, until=self.group.default_ban_group.until)
                return True
        return False


class Message(BaseModel):
    id = AutoField()
    group = ForeignKeyField(Group, backref="messages")
    mid = IntegerField(index=True)
    member = ForeignKeyField(Member, backref="messages")
    mask = CharField()
    updated = DateTimeField(default=datetime.now)
    created = DateTimeField(default=datetime.now)

    def get_redirect_for(self, member: Member):
        if member.id == self.member.id:
            return self
        else:
            rm: RedirectedMessage = self.redirects.join(Member).where(Member.id == member.id).get_or_none()
            return rm


class RedirectedMessage(BaseModel):
    id = AutoField()
    mid = IntegerField(index=True)
    message = ForeignKeyField(Message, backref="redirects")
    to_member = ForeignKeyField(Member, backref="redirected_messages")
    created = DateTimeField(default=datetime.now)


class PMBan(BaseModel):
    id = AutoField()
    from_member = ForeignKeyField(Member, null=True, backref="pm_bans")
    to_member = ForeignKeyField(Member, backref="applied_pm_bans")
    created = DateTimeField(default=datetime.now)


class PMMessage(BaseModel):
    id = AutoField()
    from_member = ForeignKeyField(Member, null=True, backref="pm_messages")
    to_member = ForeignKeyField(Member, backref="received_pm_messages")
    mid = IntegerField(index=True)
    redirected_mid = IntegerField(index=True)
    time = DateTimeField(default=datetime.now)

import asyncio
from datetime import datetime, timedelta
import random

import emoji

from ...model import Member


class MaskNotAvailable(Exception):
    pass


class UniqueMask:
    emojis = emoji.distinct_emoji_list("🐶🐱🐹🐰🦊🐼🐯🐮🦁🐸🐵🐔🐧🐥🦆🦅🦉🦄🐝🦋🐌🐙🦖🦀🐠🐳🐘🐿👻🎃🦕🐡🎄🍄🍁🐚🧸🎩🕶🐟🐬🦁🐲🪽🚤🛶")

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.lock = asyncio.Lock()
        self.users = {}
        self.masks = {}

    async def has_mask(self, member: Member):
        async with self.lock:
            return member.id in self.users

    async def mask_for(self, member: Member):
        async with self.lock:
            if member.id in self.users:
                return self.users[member.id]
            else:
                return None

    async def get_mask(self, member: Member, renew=False):
        async with self.lock:
            if member.id in self.users:
                if renew:
                    old_role = self.users[member.id]
                    role = self._get_mask()
                    self.users[member.id] = role
                    del self.masks[old_role]
                    self.masks[role] = (member.id, datetime.now())
                    return True, role
                else:
                    role = self.users[member.id]
                    self.masks[role] = (member.id, datetime.now())
                    return False, role
            else:
                role = self._get_mask()
                self.users[member.id] = role
                self.masks[role] = (member.id, datetime.now())
                return True, role

    def _get_mask(self):
        unused = [e for e in self.emojis if e not in self.masks.keys()]
        if unused:
            return random.choice(unused)
        oldest_avail = None
        for role, (uid, t) in self.masks.items():
            if t > (datetime.now() + timedelta(days=3)):
                continue
            if t < oldest_avail:
                oldest_avail = role
        if oldest_avail:
            uid, _ = self.masks[oldest_avail]
            del self.users[uid]
            return oldest_avail
        else:
            raise MaskNotAvailable()

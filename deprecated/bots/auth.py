from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import random
import re
from shutil import which
import string
from subprocess import Popen
import uuid

import openai
import toml
import dns.resolver
from loguru import logger
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message as TM
from thefuzz import process, fuzz
import aiofiles

from .. import __name__
from ..model import (
    Auth,
    Instance,
    MessageLevel,
    User,
    UserRole,
    Message,
    ValidationField,
)
from ..captcha import Captcha
from ..captcha.exceptions import CaptchaException
from ..utils import to_iterable, truncate_str, force_async
from .base import Bot
from .control import ControlBot

logger = logger.bind(scheme="auth")

answer_cache = {}


@force_async
def get_public_ip():
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = ["208.67.222.222", "208.67.220.220"]
    return resolver.resolve("myip.opendns.com")[0]


class APIError(Exception):
    pass


class AuthBot(Bot):
    name = "embykeeper_auth_bot"
    server_port_range = range(10000, 20000)

    def __init__(self, *args, services={}, captcha={}, answer={}, **kw):
        super().__init__(*args, **kw)
        self.services = services
        self.captcha_config = captcha
        self.answer_config = answer
        self.answer_library = {}
        self.servers = {}
        if self.captcha_config:
            self.captcha_provider: Captcha = Captcha.dynamicImport(self.captcha_config["provider"])
            self.captcha_provider.api_proxy = self.proxy
        if "api_key" in answer:
            openai.api_key = answer["api_key"]

    async def setup(self):
        libraries = to_iterable(self.answer_config.get("libraries", None))
        for l in libraries:
            async with aiofiles.open(l) as f:
                data = await f.read()
                questions = json.loads(data)
            for q in questions:
                try:
                    self.answer_library[q["question"]] = {
                        "options": q["options"],
                        "answer": q["answer"],
                    }
                except KeyError:
                    continue
        logger.info(f"已从本地题库读取 {len(self.answer_library)} 条问题.")

        common = filters.private & filters.text
        self.bot.add_handler(MessageHandler(self.auth, common & filters.command("auth")), group=11)
        self.bot.add_handler(MessageHandler(self.captcha, common & filters.command("captcha")), group=21)
        self.bot.add_handler(MessageHandler(self.answer, common & filters.command("answer")), group=22)
        self.bot.add_handler(MessageHandler(self.start, common & filters.command("start")), group=31)
        self.bot.add_handler(MessageHandler(self.log, common & filters.command("log")), group=32)
        self.bot.add_handler(MessageHandler(self.chatlog, common), group=15)
        logger.info(f"已启动监听: {self.bot.me.username}.")

    async def chatlog(self, client: Client, message: TM):
        cmd = truncate_str(message.text.replace("\n", " "), 40)
        logger.trace(f"[gray50]{message.from_user.name}: {cmd}[/]")

    async def response(self, message: TM, errmsg=None, error=False, **kw):
        status = "error" if error else "ok"
        data = {"command": str(message.text), "status": status, "errmsg": str(errmsg)}
        data.update(kw)
        await asyncio.sleep(0.5)
        for _ in range(3):
            msg = await self.bot.send_message(message.from_user.id, toml.dumps(data))
            if (not msg.from_user) or msg.from_user.id == self.bot.me.id:
                break
            else:
                await asyncio.sleep(1)
        logger.trace(f"[gray50]-> {message.from_user.name}: {status} {errmsg} [/]")

    @staticmethod
    def api(func):
        async def wrapper(self: AuthBot, client: Client, message: TM):
            try:
                await func(self, client, message)
            except APIError as e:
                return await self.response(message, e, error=True)

        return wrapper

    async def start(self, client: Client, message: TM):
        cmd = message.text.split()
        if len(cmd) == 1:
            msg = "欢迎使用 Embykeeper Auth, 该 Bot 仅供 Embykeeper 调用.\n" + "请使用 [Embykeeper 机器人](t.me/embykeeper_bot) 进行账户操作."
            await client.send_message(message.from_user.id, msg)

    @api
    async def auth(self, client: Client, message: TM):
        sender = message.from_user
        cmd = message.text.split()
        try:
            _, service, instance = cmd
        except ValueError:
            try:
                _, service = cmd
            except ValueError:
                raise APIError("无效参数个数") from None
            else:
                instance = uuid.UUID(int=0)
        else:
            try:
                instance = uuid.UUID(instance, version=4)
            except ValueError:
                raise APIError("无效的 instance") from None

        user, _ = await ControlBot().fetch_user(sender)
        instance, _ = Instance.get_or_create(uuid=instance)
        if user.role < UserRole.MEMBER:
            raise APIError(f"用户被封禁 ({user.role.name})")

        s = next((i for i in self.services if i["name"] == service), None)
        if s:
            requirement = UserRole(s.get("requirement", 20))
            if requirement > user.role:
                logger.debug(f'用户请求了服务 "{s["name"]}", 但其权限 {user.role.name} < {requirement.name}.')
                raise APIError(f"权限不足, 需要用户等级 {requirement.name} 但您的用户等级为 {user.role.name}")

            Auth.create(user=user, instance=instance, service=s["name"])
            logger.debug(f"服务认证通过: {s['name']} => {sender.name} ({user.uid}).")
            return await self.response(message, "鉴权通过")
        else:
            try:
                field = ValidationField[service.upper()]
            except KeyError:
                raise APIError("未知的 service") from None
            if user.validate(field):
                Auth.create(user=user, instance=instance, service=service)
                logger.debug(f"服务认证通过: {service} => {sender.name} ({user.uid}).")
                return await self.response(message, "鉴权通过")
            else:
                raise APIError(f"权限不足, 该功能是时长付费定制项目, 需要您通过爱发电购买")

    @api
    async def log(self, client: Client, message: TM):
        sender = message.from_user
        cmd = message.text.split(None, 2)
        try:
            _, instance, log = cmd
        except ValueError:
            try:
                _, log = cmd
            except ValueError:
                raise APIError("无效参数个数") from None
            else:
                instance = uuid.UUID(int=0)

        try:
            instance = uuid.UUID(instance, version=4)
        except ValueError:
            raise APIError("无效的 instance") from None

        try:
            level, content = log.split("#", 1)
        except ValueError:
            raise APIError("无效的 log") from None

        user, _ = await ControlBot().fetch_user(sender)
        instance, _ = Instance.get_or_create(uuid=instance)
        if user.role < UserRole.MEMBER:
            raise APIError(f"用户被封禁 ({user.role.name})")

        level = MessageLevel[level]

        Message.create(instance=instance, user=user, level=level, content=content)

        if level > MessageLevel.WARNING:
            msg = truncate_str(content.replace("\n", " "), 200)
            logger.debug(f"接收日志: {sender.name}: {msg}.")
        else:
            msg = truncate_str(content.replace("\n", " "), 40)
            logger.debug(f"接收日志: {sender.name}: {msg}.")

        return await self.response(message, "日志已接收")

    @api
    async def answer(self, client: Client, message: TM):
        sender = message.from_user
        try:
            _, instance, question = message.text.split(None, 2)
        except ValueError:
            try:
                _, question = message.text.split(None, 1)
            except ValueError:
                raise APIError("无效参数个数") from None
            else:
                instance = uuid.UUID(int=0)

        try:
            instance = uuid.UUID(instance, version=4)
        except ValueError:
            raise APIError("无效的 instance") from None

        if not self.answer_config:
            logger.warning("用户请求了问题回答, 但没有配置 API.")
            raise APIError("服务端错误, 请稍后重试")

        user, _ = await ControlBot().fetch_user(sender)
        instance, _ = Instance.get_or_create(uuid=instance)
        if user.role < UserRole.MEMBER:
            raise APIError(f"用户被封禁 ({user.role.name})")

        requirement = UserRole(self.answer_config["requirement"])
        if user.role < requirement:
            logger.debug(f"用户请求了问题回答, 但其权限 {user.role.name} < {requirement.name}.")
            raise APIError(f"权限不足, 需要 {requirement.name}")

        if user.validate(ValidationField.ANSWER_BY_LIBRARY):
            result, score = process.extractOne(question, self.answer_library.keys(), scorer=fuzz.partial_ratio)

            if score > 80:
                logger.debug(f"收到来自 {sender.name} 的问题回答请求, 并从本地题库找到答案.")
                await self.response(
                    message,
                    "回答成功",
                    answer=self.answer_library[result]["answer"],
                    by="高准确题库",
                )
                return

        period = datetime.now() - timedelta(hours=12)
        limit = self.answer_config["limit"]
        used = Auth.select().where(Auth.service == "answer", Auth.time > period).join(User).where(User.id == user.id).group_by(Auth).count()
        if used > limit:
            if not user.role == UserRole.CREATOR:
                logger.debug(f'用户请求了问题回答, 但其调用次数 "{used}" > "{limit}".')
                raise APIError(f"访问超限, 12小时内最多调用{limit}次")

        question = str(self.answer_config.get("prefix", "")) + "\n" + question + "\n" + str(self.answer_config.get("suffix", ""))
        logger.debug(f"收到来自 {sender.name} 的问题回答请求, 开始解析.")
        cache = answer_cache.get(question, None)
        if cache:
            if isinstance(cache, asyncio.Event):
                logger.debug(f"收到来自 {sender.name} 的问题回答请求, 将等待其他协程解析.")
                try:
                    await asyncio.wait_for(cache.wait(), 10)
                except asyncio.TimeoutError:
                    logger.debug(f"用户 {sender.name} 等待其他协程超时.")
                    raise APIError("服务端错误, 解析超时, 请稍后重试") from None
            else:
                logger.debug(f"{sender.name} 的问题回答请求, 将通过答案缓存解析.")
            result = answer_cache[question]
        else:
            answer_cache[question] = ok = asyncio.Event()
            try:
                completion = await asyncio.wait_for(
                    openai.ChatCompletion.acreate(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": question}],
                        max_tokens=200,
                    ),
                    10,
                )
                result = completion.choices[0].message.content
            except openai.OpenAIError as e:
                logger.info(f"用户 {sender.name} 访问问题回答 API 错误: {e}")
                raise APIError("服务端错误, 请稍后重试") from None
            except asyncio.TimeoutError:
                logger.info(f"用户 {sender.name} 访问问题回答 API 超时.")
                raise APIError("服务端错误, 解析超时, 请稍后重试") from None
            if not result:
                logger.info(f"用户 {sender.name} 访问问题回答 API 返回错误超限.")
                raise APIError("服务端错误, 请稍后重试") from None
            else:
                answer_cache[question] = result
                ok.set()

        match = re.search(r"(?<!\S)[A-D](?!\S)", result)
        if match:
            result = match.group(0)
        else:
            logger.info(f"用户 {sender.name} 问题回答失败: 不是有效回答.")
            raise APIError("无法解析答案, 确认问题格式正确") from None

        logger.info(f"用户 {sender.name} 问题回答成功.")
        Auth.create(user=user, instance=instance, service="answer")
        await self.response(message, "回答成功", answer=result, by="ChatGPT")

    @api
    async def captcha(self, client: Client, message: TM):
        sender = message.from_user
        try:
            _, instance = message.text.split()
        except ValueError:
            instance = uuid.UUID(int=0)
        else:
            try:
                instance = uuid.UUID(instance, version=4)
            except ValueError:
                raise APIError("无效的 instance") from None

        if not self.captcha_config:
            logger.warning(f"用户 {sender.name} 请求了验证码跳过, 但没有配置 API.")
            raise APIError("服务端错误, 请稍后重试")

        if not which("microsocks"):
            logger.warning(f"用户 {sender.name} 请求了验证码跳过, 但没有安装 microsocks.")
            raise APIError("服务端错误, 请稍后重试")

        user, _ = await ControlBot().fetch_user(sender)
        instance, _ = Instance.get_or_create(uuid=instance)
        if user.role < UserRole.MEMBER:
            raise APIError(f"用户被封禁 ({user.role.name})")

        requirement = UserRole(self.captcha_config["requirement"])
        if user.role < requirement:
            logger.debug(f"用户 {sender.name} 请求了验证码跳过, 但其权限 {user.role.name} < {requirement.name}.")
            raise APIError(f"权限不足, 需要 {requirement.name}")

        period = datetime.now() - timedelta(hours=12)
        limit = self.captcha_config["limit"]
        if user.role >= UserRole.SUPER:
            limit = limit * 4
        used = (
            Auth.select().where(Auth.service == "captcha", Auth.time > period).join(User).where(User.id == user.id).group_by(Auth).count()
        )
        if used > limit:
            if not user.role == UserRole.CREATOR:
                logger.debug(f'用户 {sender.name} 请求了验证码跳过, 但其调用次数 "{used}" > "{limit}".')
                raise APIError(f"访问超限, 12小时内最多调用{limit}次")

        avail_port = set(self.server_port_range) - set(self.servers.keys())
        if not avail_port:
            logger.warning(f"用户 {sender.name} 请求了验证码跳过, 但代理池不足.")
            raise APIError(f"代理池不足, 请稍后重试")

        proxy_port = str(random.choice(tuple(avail_port)))
        proxy_host = self.captcha_config.get("proxy_host", None)
        if not proxy_host:
            proxy_host = await get_public_ip()
        proxy_user = str(sender.id)
        proxy_pass = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
        proxy_spec = f"socks5://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"

        self.servers[proxy_port] = proc = Popen(["microsocks", "-q", "-p", proxy_port, "-u", proxy_user, "-P", proxy_pass])
        try:
            logger.debug(f'收到来自 {sender.name} 的验证码请求, 在 "{proxy_spec}" 开启了代理.')
            await asyncio.sleep(5)
            try:
                ret = await self.captcha_provider.getCaptchaAnswer(
                    captchaType=self.captcha_config["type"],
                    url=self.captcha_config["url"],
                    siteKey=self.captcha_config["site_key"],
                    captchaParams={
                        "clientKey": self.captcha_config["client_key"],
                        "proxy": {"https": proxy_spec},
                    },
                )
            except CaptchaException as e:
                logger.warning(f"访问验证码 API 出现错误: {e}.")
                raise APIError("服务端错误, 请稍后重试") from None

            try:
                token, useragent = ret
            except ValueError:
                token = ret
                useragent = None

            Auth.create(user=user, instance=instance, service="captcha")
            logger.debug(f"{sender.name} 请求的验证码解析成功, 等待请求后关闭代理.")
            await self.response(
                message,
                "验证码 token 获取成功",
                token=token,
                useragent=useragent,
                proxy=proxy_spec,
            )
            await asyncio.sleep(120)
        finally:
            logger.debug(f"超时或停止, 代理关闭.")
            proc.kill()

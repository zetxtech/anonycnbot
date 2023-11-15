## Anonycnbot

**Anonycnbot** 是一个用于创建完全匿名群组的机器人.  ([@anonycnbot](https://t.me/anonycnbot)).

[![Screenshot](https://github.com/anonycnbot/.github/raw/main/images/button.svg)](https://t.me/anonycnbot)

### 特点
1. 创建的匿名群组会以机器人的形式存在, 所有人的消息都将向所有成员广播. 
2. 所有身份信息都会被隐藏, 包括姓名、用户名、头像、在线状态、输入状态等等, 用户之间会通过一个Emoji面具区分. 
3. 内置了群管理工具, 比如封禁、欢迎消息、置顶消息等等. 
4. 仅存储消息ID, 消息内容将不会被存储, 充分考虑隐私性. 

### 使用方法
你需要前往 [@anonycnbot](https://t.me/anonycnbot), 然后按照机器人的指示操作. 简单来说, 包含以下步骤: 
1. 在 [@anonycnbot](https://t.me/anonycnbot) 中点击“创建新群组”. 
2. 在 [@botfather](https://t.me/botfather) 中创建一个新的机器人, 并将机器人的令牌转发给 [@anonycnbot](https://t.me/anonycnbot). 
3. 此时新的机器人就成为了新的匿名群组, 试试看吧!

### 自部署
新建一个 `config.toml`:

```toml
[tele]
api_id = "12345678"
api_hash = "abcde1234567890abcde1234567890"

[father]
token = "12345678:AbCdEfG-123456789"
```

您自行部署的版本应该在`/start`界面清晰标识此存储库为来源.  谢谢. 

### 英文版 / English Version
Please use [@anonyabbot](https://t.me/anonyabbot).

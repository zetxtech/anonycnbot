from github import Github

readme = """
## 欢迎您, {username}
感谢您的贡献, 邀请您加入 Embykeeper 高级会员, 这是您的邀请码:
```
{code}
```
请前往 [Embykeeper Bot](https://t.me/embykeeper_bot) 兑换
""".strip()


def create_invite_repo(token, name, username, code):
    g = Github(token)
    org = g.get_organization("embykeeper")
    repo = org.create_repo(name=name, private=True, description="感谢您对项目的贡献, 欢迎您加入 Embykeeper 高级会员")
    repo.create_file("README.md", "Initial commit", readme.format(username=username, code=code))
    repo.add_to_collaborators(username, permission="pull")


def remove_repo(token, name):
    g = Github(token)
    org = g.get_organization("embykeeper")
    repo = org.get_repo(name)
    repo.delete()

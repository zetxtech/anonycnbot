from pyrubrum import transform

import anonyabbot


class Tree:
    @property
    def tree(self: "anonyabbot.FatherBot"):
        M = self._menu
        L = self._link
        P = self._page
        K = self._keyboard
        menu = {
            M("start", default=True): {
                M("my_info", "ℹ️ 个人信息"): {
                    M("create_code", "🔗 创建邀请链接"): None,
                    M("use_code", "🗝️ 兑换角色码"): None,
                },
                M("new_group", "➕ 新建群组"): {L("botfather", "前往 @botfather", url="t.me/botfather")},
                P(
                    "list_group",
                    "⚒️ 我的群组",
                    "ℹ️ 创建的群组: ",
                    extras="new_group",
                ): {M("jump_group_detail")},
                L("feedback_group", "💬 反馈", url="t.me/anonycnbot_chat_bot"): None,
            },
            M("_group_detail", back="list_group"): {
                M("edit_group_profile", "⚒️ 群组资料", "ℹ️ 群组头像和描述只能在 @botfather 中编辑"): {
                    L("botfather_group", "前往 @botfather", url="t.me/botfather")
                },
                M("delete_group_confirm", "🗑️ 删除群组"): {M("delete_group", "⚠️ 确定")},
            },
            M("admin"): {
                K("generate_codes_select_role", "👑 生成代码", "ℹ️ 选择角色", extras="_generate_codes_select_days"): {
                    M("gcsr_select")
                },
                P(
                    "list_group_all",
                    "⚒️ 管理群组",
                    "ℹ️ 所有群组: ",
                    extras=["_lga_switch_activity", "_lga_switch_member"],
                ): {M("jump_group_detail_admin")},
            },
            K("_generate_codes_select_days", display="ℹ️ 选择时间", items=[30, 60, 90, 180, 360, 1080, 3600]): {
                K("generate_codes_select_num", display="ℹ️ 选择数量", items=[1, 5, 10, 20]): {M("generate_codes", back="admin")}
            },
            M("_lga_switch_activity"): None,
            M("_lga_switch_member"): None,
            M("_group_detail_admin", back="list_group_all"): {
                M("admin_delete_group_confirm", "🗑️ 删除群组"): {M("admin_delete_group", "⚠️ 是的, 我确定")},
            },
        }

        return transform(menu)

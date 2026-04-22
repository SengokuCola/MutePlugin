# MutePlugin

群聊禁言管理插件，用于让麦麦在群聊中执行禁言操作。

## 功能

- 智能禁言：麦麦可在需要时调用禁言工具。
- 手动命令：可选开启 `/mute` 命令进行禁言。
- 权限保护：可限制命令使用者，也可设置不会被插件禁言的用户。

## 配置

主要配置位于 `config.toml`：

- `plugin.enabled`：是否启用插件。
- `components.enable_smart_mute`：是否启用智能禁言。
- `components.enable_mute_command`：是否启用 `/mute` 命令，默认关闭。
- `permissions.allowed_groups`：允许智能禁言生效的群，空列表表示不限制。
- `permissions.allowed_users`：允许使用 `/mute` 命令的用户，空列表表示不限制。
- `permissions.admin_users`：保护用户列表，列表内用户不会被插件禁言。
- `mute.min_duration` / `mute.max_duration`：禁言时长上下限，单位秒。

用户和群号格式推荐使用 `platform:id`，例如：

```toml
allowed_groups = ["qq:123456789"]
allowed_users = ["qq:10001"]
admin_users = ["qq:10002"]
```

## 手动命令

启用 `components.enable_mute_command = true` 后，可以使用：

```text
/mute <人物名> <秒数> [原因]
```

示例：

```text
/mute 张三 300 刷屏
```

命令成功后只执行禁言，不会额外发送成功提示消息；失败、权限不足或参数错误时会发送错误提示。

## 注意事项

- 插件依赖 NapCat 群禁言接口，机器人需要具备对应群管理权限。
- 禁言目标会通过人物名称解析到平台用户 ID，请尽量使用麦麦已认识的人物名。
- 群主和保护列表中的用户不会被禁言。

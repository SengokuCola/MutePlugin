"""MutePlugin 的 maibot_sdk 实现。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool


def _matches_scoped_identifier(allowed_values: List[str], current_value: str) -> bool:
    """兼容 `platform:id` 与纯 ID 两种配置格式。"""

    normalized_current_value = str(current_value or "").strip()
    if not normalized_current_value:
        return False

    for allowed_value in allowed_values:
        normalized_allowed_value = str(allowed_value or "").strip()
        if not normalized_allowed_value:
            continue
        if normalized_allowed_value == normalized_current_value:
            return True
        if normalized_allowed_value.endswith(f":{normalized_current_value}"):
            return True
    return False


def _extract_nested_capability_value(payload: Any, expected_key: str) -> Any:
    """兼容 Host 侧返回的多层 capability 包装结果。"""

    current = payload
    visited: set[int] = set()
    while isinstance(current, dict):
        current_id = id(current)
        if current_id in visited:
            break
        visited.add(current_id)

        if expected_key in current:
            return current.get(expected_key)
        if "result" in current:
            current = current.get("result")
            continue
        break
    return payload


def _extract_nested_mapping(payload: Any) -> Dict[str, Any]:
    """从 capability / API 返回值中剥离常见包装层，取出业务字典。"""

    current = payload
    visited: set[int] = set()
    while isinstance(current, dict):
        current_id = id(current)
        if current_id in visited:
            break
        visited.add(current_id)

        for wrapper_key in ("result", "data"):
            nested_value = current.get(wrapper_key)
            if isinstance(nested_value, dict):
                current = nested_value
                break
        else:
            return current
    return {}


def _normalize_platform_user_id(payload: Any) -> str:
    """从 capability 返回值中提取最终可用的平台用户 ID。"""

    raw_value = _extract_nested_capability_value(payload, "value")
    if isinstance(raw_value, dict):
        for candidate_key in ("user_id", "qq_id", "id", "value"):
            candidate_value = raw_value.get(candidate_key)
            normalized_candidate = str(candidate_value or "").strip()
            if normalized_candidate:
                return normalized_candidate
        return ""
    return str(raw_value or "").strip()


def _extract_api_error_message(payload: Any) -> str:
    """从 API 返回值中提取错误消息。"""

    current = payload
    visited: set[int] = set()
    while isinstance(current, dict):
        current_id = id(current)
        if current_id in visited:
            break
        visited.add(current_id)

        error_message = str(current.get("error") or current.get("message") or "").strip()
        if error_message:
            return error_message

        if "result" in current:
            current = current.get("result")
            continue
        break
    return ""


def _is_successful_api_result(payload: Any) -> bool:
    """判断 API 调用结果是否表示成功。"""

    current = payload
    visited: set[int] = set()
    while isinstance(current, dict):
        current_id = id(current)
        if current_id in visited:
            break
        visited.add(current_id)

        status = str(current.get("status") or "").strip().lower()
        retcode = current.get("retcode")
        success = current.get("success")
        if status == "ok":
            return True
        if success is True and (retcode in (None, 0, "0") or "result" in current):
            return True
        if "result" in current:
            current = current.get("result")
            continue
        break
    return False


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="4.5.0", description="配置版本")


class ComponentsConfig(PluginConfigBase):
    """组件启用控制。"""

    __ui_label__ = "组件"
    __ui_icon__ = "toggle-right"
    __ui_order__ = 1

    enable_smart_mute: bool = Field(default=True, description="是否启用智能禁言工具")
    enable_mute_command: bool = Field(default=False, description="是否启用禁言命令")


class PermissionsConfig(PluginConfigBase):
    """权限控制配置。"""

    __ui_label__ = "权限"
    __ui_icon__ = "shield"
    __ui_order__ = 2

    admin_users: List[str] = Field(default_factory=list, description="这些用户不会被插件禁言")
    allowed_users: List[str] = Field(default_factory=list, description="允许使用命令的用户列表")
    allowed_groups: List[str] = Field(default_factory=list, description="允许使用禁言工具的群列表")


class MuteConfig(PluginConfigBase):
    """核心禁言配置。"""

    __ui_label__ = "禁言"
    __ui_icon__ = "volume-x"
    __ui_order__ = 3

    min_duration: int = Field(default=60, description="最短禁言时长，单位秒")
    max_duration: int = Field(default=2592000, description="最长禁言时长，单位秒")
    default_duration: int = Field(default=300, description="默认禁言时长，单位秒")
    enable_duration_formatting: bool = Field(default=True, description="是否格式化禁言时长")
    log_mute_history: bool = Field(default=True, description="是否记录禁言历史")
    error_messages: List[str] = Field(
        default_factory=lambda: [
            "没有指定禁言对象哦",
            "没有指定禁言时长哦",
            "禁言时长必须是正整数哦~",
            "禁言时长必须是数字哦~",
            "找不到 {target} 这个人呢~",
            "查询用户信息时出现问题了",
        ],
        description="执行禁言失败时可用的错误消息模板",
    )


class LoggingConfig(PluginConfigBase):
    """日志配置。"""

    __ui_label__ = "日志"
    __ui_icon__ = "scroll-text"
    __ui_order__ = 4

    level: str = Field(default="INFO", description="日志级别")
    prefix: str = Field(default="[MutePlugin]", description="日志前缀")
    include_user_info: bool = Field(default=True, description="日志中是否带用户信息")
    include_duration_info: bool = Field(default=True, description="日志中是否带禁言时长")


class MutePluginConfig(PluginConfigBase):
    """MutePlugin 配置模型。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    components: ComponentsConfig = Field(default_factory=ComponentsConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    mute: MuteConfig = Field(default_factory=MuteConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class MutePlugin(MaiBotPlugin):
    """群聊禁言管理插件。"""

    config_model = MutePluginConfig

    async def on_load(self) -> None:
        """处理插件加载。"""

    async def on_config_update(self, scope: str, config_data: Dict[str, object], version: str) -> None:
        """处理配置热更新。"""

        del scope
        del config_data
        del version

    def get_components(self) -> List[Dict[str, Any]]:
        """返回组件声明，并在暴露阶段限制禁言工具可用群。"""

        components = super().get_components()
        allowed_groups = [
            str(group_id).strip()
            for group_id in self.config.permissions.allowed_groups
            if str(group_id).strip()
        ]
        for component in components:
            if component.get("name") != "mute":
                continue
            component["chat_scope"] = "group"
            component["allowed_session"] = allowed_groups
        return components

    def _log_prefix(self) -> str:
        return self.config.logging.prefix

    def _format_duration(self, seconds: int) -> str:
        """格式化禁言时长。"""

        if not self.config.mute.enable_duration_formatting:
            return f"{seconds}秒"

        if seconds < 60:
            return f"{seconds}秒"
        if seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}分钟{remaining_seconds}秒" if remaining_seconds else f"{minutes}分钟"
        if seconds < 86400:
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            return f"{hours}小时{remaining_minutes}分钟" if remaining_minutes else f"{hours}小时"

        days = seconds // 86400
        remaining_hours = (seconds % 86400) // 3600
        return f"{days}天{remaining_hours}小时" if remaining_hours else f"{days}天"

    def _normalize_duration(self, duration_text: Any) -> Tuple[Optional[int], Optional[str]]:
        """校验并归一化禁言时长。"""

        if duration_text in (None, ""):
            return None, self.config.mute.error_messages[1]

        try:
            duration = int(str(duration_text).strip())
        except (TypeError, ValueError):
            return None, self.config.mute.error_messages[3]

        if duration <= 0:
            return None, self.config.mute.error_messages[2]

        if duration < self.config.mute.min_duration:
            duration = self.config.mute.min_duration
        if duration > self.config.mute.max_duration:
            duration = self.config.mute.max_duration
        return duration, None

    def _is_admin_user(self, user_id: str) -> bool:
        return _matches_scoped_identifier(self.config.permissions.admin_users, user_id)

    def _can_use_command(self, user_id: str) -> bool:
        allowed_users = self.config.permissions.allowed_users
        if not allowed_users:
            return True
        return _matches_scoped_identifier(allowed_users, user_id)

    async def _resolve_person_user_id(self, person_name: str) -> Tuple[Optional[str], Optional[str]]:
        """根据人物名称解析平台用户 ID。"""

        normalized_person_name = str(person_name or "").strip()
        if not normalized_person_name:
            return None, self.config.mute.error_messages[0]

        person_id_response = await self.ctx.person.get_id_by_name(normalized_person_name)
        person_id = str(_extract_nested_capability_value(person_id_response, "person_id") or "").strip()
        if not person_id:
            return None, self.config.mute.error_messages[4].format(target=normalized_person_name)

        user_id_response = await self.ctx.person.get_value(person_id, "user_id")
        normalized_user_id = _normalize_platform_user_id(user_id_response)
        if not normalized_user_id or normalized_user_id == "unknown":
            self.ctx.logger.warning(
                "%s 未能解析人物 user_id: person_name=%s, person_id=%s, raw_response=%s",
                self._log_prefix(),
                normalized_person_name,
                person_id,
                user_id_response,
            )
            return None, self.config.mute.error_messages[5]
        return normalized_user_id, None

    async def _resolve_message_sender(self, stream_id: str, msg_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """根据消息 ID 查询消息，并返回发送者用户 ID 与展示名。"""

        normalized_stream_id = str(stream_id or "").strip()
        normalized_msg_id = str(msg_id or "").strip()
        if not normalized_msg_id:
            return None, None, "缺少目标消息 ID"
        if not normalized_stream_id:
            return None, None, "缺少当前会话 stream_id，无法按消息 ID 查询目标"

        lookup_result = await self.ctx.call_capability(
            "message.get_by_id",
            message_id=normalized_msg_id,
            chat_id=normalized_stream_id,
        )
        if not isinstance(lookup_result, dict):
            raise RuntimeError("message.get_by_id 返回格式异常")
        if lookup_result.get("success") is False:
            raise RuntimeError(str(lookup_result.get("error") or "message.get_by_id 查询失败"))

        target_message = lookup_result.get("message")
        if target_message is None:
            return None, None, f"未找到消息 ID 为 {normalized_msg_id} 的消息"
        if not isinstance(target_message, dict):
            raise RuntimeError("message.get_by_id 返回的 message 字段格式异常")

        message_info = target_message.get("message_info")
        user_info = message_info.get("user_info") if isinstance(message_info, dict) else None
        if not isinstance(user_info, dict):
            return None, None, f"消息 {normalized_msg_id} 缺少发送者信息"

        user_id = str(user_info.get("user_id") or "").strip()
        if not user_id:
            return None, None, f"消息 {normalized_msg_id} 缺少发送者 ID"
        display_name = (
            str(user_info.get("user_cardname") or "").strip()
            or str(user_info.get("user_nickname") or "").strip()
            or user_id
        )
        return user_id, display_name, None

    async def _get_group_member_role(self, group_id: str, user_id: str) -> str:
        """查询目标在群内的角色。"""

        result = await self.ctx.api.call(
            "adapter.napcat.group.get_group_member_info",
            version="1",
            group_id=str(group_id),
            user_id=str(user_id),
            no_cache=True,
        )
        member_info = _extract_nested_mapping(result)
        return str(member_info.get("role") or "").strip().lower()

    async def _check_ban_target_constraints(
        self,
        *,
        group_id: str,
        user_id: str,
        target_name: str,
    ) -> Optional[str]:
        """在执行禁言前检查目标限制。"""

        role = await self._get_group_member_role(group_id, user_id)
        if role == "owner":
            return f"{target_name} 是群主，不能被禁言"
        if role == "admin":
            return f"{target_name} 是管理员，不能被禁言"
        return None

    async def _send_group_ban(
        self,
        *,
        group_id: str,
        stream_id: str,
        user_id: str,
        duration: int,
        target_name: str,
        reason: str,
    ) -> Tuple[bool, Optional[str]]:
        """通过 NapCat Adapter 新 API 执行群禁言。"""

        normalized_group_id = str(group_id or "").strip()
        normalized_user_id = str(user_id or "").strip()
        if not normalized_group_id:
            await self.ctx.send.text("当前会话缺少群号，无法执行禁言", stream_id)
            return False, "当前会话缺少群号"
        if not normalized_user_id:
            await self.ctx.send.text("未能解析目标用户 ID，无法执行禁言", stream_id)
            return False, "未能解析目标用户 ID"

        result = await self.ctx.api.call(
            "adapter.napcat.group.set_group_ban",
            version="1",
            group_id=normalized_group_id,
            user_id=normalized_user_id,
            duration=duration,
        )
        success = _is_successful_api_result(result)
        if not success:
            error_message = _extract_api_error_message(result)
            self.ctx.logger.warning(
                "%s 禁言调用失败: group_id=%s, user_id=%s, result=%s",
                self._log_prefix(),
                normalized_group_id,
                normalized_user_id,
                result,
            )
            if "cannot ban owner" in error_message.lower():
                return False, f"{target_name} 是群主，不能被禁言"
            return False, error_message or "执行禁言动作失败"

        self.ctx.logger.info(
            "%s 已调用 adapter.napcat.group.set_group_ban: group_id=%s, user_id=%s, target=%s, duration=%s, reason=%s",
            self._log_prefix(),
            normalized_group_id,
            normalized_user_id,
            target_name,
            str(duration),
            reason,
        )
        return True, None

    @Tool(
        "mute",
        description=(
            "在群聊中根据消息 ID 对该消息发送者执行禁言。\n"
            "适用于刷屏、违规发言、用户主动要求被禁言等情况。\n"
            "当有人发送了不当内容或者辱骂他人时，可以对其禁言。\n"
            "调用前应确认 msg_id 指向要处理的目标用户消息，且不要对管理员保护名单中的用户执行。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "msg_id": {
                    "type": "string",
                    "description": "要禁言的目标用户所发送的消息 ID",
                },
                "duration": {
                    "type": "integer",
                    "description": "禁言时长，单位秒，必须是正整数",
                },
                "reason": {
                    "type": "string",
                    "description": "禁言原因，可选",
                },
            },
            "required": ["msg_id", "duration"],
        },
    )
    async def handle_mute_tool(
        self,
        stream_id: str = "",
        group_id: str = "",
        msg_id: str = "",
        duration: Any = None,
        reason: str = "",
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """执行禁言工具。"""

        del kwargs

        if not self.config.components.enable_smart_mute:
            return False, "智能禁言未启用"
        if not stream_id:
            return False, "无法获取当前会话"

        normalized_group_id = str(group_id or "").strip()
        if not normalized_group_id:
            return False, "当前会话缺少群号"

        normalized_msg_id = str(msg_id or "").strip()
        if not normalized_msg_id:
            return False, "缺少目标消息 ID"

        normalized_duration, duration_error = self._normalize_duration(duration)
        if normalized_duration is None:
            return False, duration_error or "禁言时长无效"

        target_user_id, target_display_name, resolve_error = await self._resolve_message_sender(
            stream_id,
            normalized_msg_id,
        )
        if not target_user_id:
            return False, resolve_error or self.config.mute.error_messages[5]
        if self._is_admin_user(target_user_id):
            return False, f"用户 {target_display_name} 是管理员，无法被禁言"
        constraint_error = await self._check_ban_target_constraints(
            group_id=normalized_group_id,
            user_id=target_user_id,
            target_name=target_display_name,
        )
        if constraint_error:
            return False, constraint_error

        normalized_reason = str(reason or "违反群规").strip() or "违反群规"
        success, send_error = await self._send_group_ban(
            group_id=normalized_group_id,
            stream_id=stream_id,
            user_id=target_user_id,
            duration=normalized_duration,
            target_name=target_display_name,
            reason=normalized_reason,
        )
        if not success:
            return False, send_error or "执行禁言动作失败"
        return True, f"成功禁言 {target_display_name}"

    @Command(
        "mute_command",
        description="禁言命令，手动执行禁言操作",
        pattern=r"^/mute\s+(?P<target>\S+)\s+(?P<duration>\d+)(?:\s+(?P<reason>.+))?$",
    )
    async def handle_mute_command(
        self,
        stream_id: str = "",
        group_id: str = "",
        user_id: str = "",
        matched_groups: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Tuple[bool, Optional[str], bool]:
        """执行禁言命令。"""

        del kwargs

        if not self.config.components.enable_mute_command:
            return False, "禁言命令未启用", True
        if not stream_id:
            return False, "无法获取聊天流信息", True

        normalized_group_id = str(group_id or "").strip()
        if not normalized_group_id:
            await self.ctx.send.text("当前会话缺少群号，无法执行禁言", stream_id)
            return False, "当前会话缺少群号", True
        if not self._can_use_command(user_id):
            await self.ctx.send.text("你没有使用禁言命令的权限", stream_id)
            return False, "你没有使用禁言命令的权限", True

        groups = matched_groups or {}
        target_name = str(groups.get("target") or "").strip()
        duration_text = groups.get("duration")
        reason = str(groups.get("reason") or "管理员操作").strip() or "管理员操作"

        if not target_name or duration_text in (None, ""):
            await self.ctx.send.text("命令参数不完整，请检查格式", stream_id)
            return False, "命令参数不完整", True

        normalized_duration, duration_error = self._normalize_duration(duration_text)
        if normalized_duration is None:
            await self.ctx.send.text(duration_error or "禁言时长无效", stream_id)
            return False, duration_error or "禁言时长无效", True

        target_user_id, resolve_error = await self._resolve_person_user_id(target_name)
        if not target_user_id:
            await self.ctx.send.text(resolve_error or self.config.mute.error_messages[5], stream_id)
            return False, resolve_error or self.config.mute.error_messages[5], True
        if self._is_admin_user(target_user_id):
            await self.ctx.send.text(f"用户 {target_name} 是管理员，无法被禁言", stream_id)
            return False, "管理员无法被禁言", True
        constraint_error = await self._check_ban_target_constraints(
            group_id=normalized_group_id,
            user_id=target_user_id,
            target_name=target_name,
        )
        if constraint_error:
            await self.ctx.send.text(constraint_error, stream_id)
            return False, constraint_error, True

        success, send_error = await self._send_group_ban(
            group_id=normalized_group_id,
            stream_id=stream_id,
            user_id=target_user_id,
            duration=normalized_duration,
            target_name=target_name,
            reason=reason,
        )
        if not success:
            await self.ctx.send.text(send_error or "发送禁言命令失败", stream_id)
            return False, send_error or "发送禁言命令失败", True

        return True, f"成功禁言 {target_name}", True


def create_plugin() -> MutePlugin:
    """创建插件实例。"""

    return MutePlugin()

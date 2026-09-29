"""错误码与错误映射契约（执行文档 v1.2 §2.5 / §21.2 / §21.3）。"""

from __future__ import annotations

from typing import Dict, Optional

from .enums import ErrorCode


class TransportError(Exception):
    """传输层异常。携带统一错误码，便于上层按 §12.5 降级与审计。"""

    def __init__(self, code: ErrorCode, message: str,
                 http_status: Optional[int] = None,
                 body: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.body = body

    def __str__(self) -> str:  # pragma: no cover - 便利方法
        return f"[{self.code}] {self.message}"


def error_for_http_status(status: int) -> ErrorCode:
    """把 sidecar 的 HTTP 状态映射为统一错误码（§2.5）。

    - 5xx → ``E_LLM_001``（服务/超时类）
    - 4xx → ``E_LLM_002``（请求/格式类）
    - 其余（异常状态）→ ``E_LLM_001``
    """
    if 500 <= status <= 599:
        return ErrorCode.LLM_001
    if 400 <= status <= 499:
        return ErrorCode.LLM_002
    return ErrorCode.LLM_001


# §21.3 用户可读错误信息（含可操作建议）
USER_MESSAGES: Dict[ErrorCode, str] = {
    ErrorCode.PARSE_001: "无法识别剧本格式。建议改用 Fountain(.fountain) 或纯文本(.txt)。",
    ErrorCode.SDL_001: "场景描述校验未通过。请检查镜头、角色与道具的 ID 引用是否完整。",
    ErrorCode.SDL_002: "旧版项目文件迁移失败。建议用当前版本重新生成，或手工修正 project.bdproj。",
    ErrorCode.AXIS_001: ("相机位置违反 180° 轴线规则，可能导致角色左右方向混乱。"
                         "建议将相机移到轴线另一侧，或插入中性镜头过渡。"),
    ErrorCode.SPACE_001: "角色或相机与墙体/道具重叠。建议调整位置或扩大房间尺寸。",
    ErrorCode.CAM_001: ("在当前房间尺寸下找不到满足该景别的机位。"
                        "建议改用更短焦距、更换景别，或扩大房间。"),
    ErrorCode.EXEC_001: "场景对象创建失败。已自动回滚本步操作，可重试或简化该镜头。",
    ErrorCode.LLM_001: "LLM 服务无响应或超时。建议检查网络、API Key 与配额，或切换到本地模型端点。",
    ErrorCode.LLM_002: "LLM 返回内容不符合约定结构。已自动重试一次；若反复失败请降低温度或更换模型。",
    ErrorCode.LLM_003: "本次运行的 LLM 预算已耗尽。可在设置中提高上限，或缩小剧本范围。",
    ErrorCode.TOOL_001: "工具参数校验失败。参数已反馈给模型，将尝试自我修正。",
    ErrorCode.TOOL_002: "工具调用次数超出上限。已按降级策略收尾该镜头。",
    ErrorCode.TOOL_003: "动作组合冲突（如边走边摔倒）。请先结束当前动作，或改用兼容动作。",
    ErrorCode.DELIV_001: ("以下对象会出现在参考视频中：{objects}。"
                          "请将它们移入 BlockDirector/Guides 集合或设为不可渲染。"),
    ErrorCode.DELIV_002: "视频编码失败，已降级为 PNG 序列输出。",
    ErrorCode.CORR_001: "自纠错次数超过上限。该镜头已跳过并标注为降级。",
    ErrorCode.SCRIPT_001: ("剧本声明的镜头数/顺序/景别/时长或对白与计划不一致。"
                           "建议检查分镜表的「预估时长」「总时长」与台词归属，"
                           "或放宽 dialogue.declared_tolerance_s。"),
    ErrorCode.BRIEF_001: ("剧本理解（阶段 S）失败：模型两次都没有返回合法的"
                          "SceneBrief。已退回确定性抽取（不猜代词），"
                          "说话对象与注视关系可能缺失。"),
}


def user_message(code: ErrorCode, **fmt: object) -> str:
    """返回用户可读信息；缺失模板时回退到错误码本身。"""
    template = USER_MESSAGES.get(code, str(code))
    if fmt:
        try:
            return template.format(**fmt)
        except (KeyError, IndexError):
            return template
    return template

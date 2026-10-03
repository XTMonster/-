"""项目文件读写（执行文档 v1.2 §14.1 / §14.2）。

`project.bdproj` 是 JSON：SDL + 元数据。加载时先跑版本迁移（§5.3），再校验，
最后才交给执行引擎重建场景——顺序不能反，否则旧项目会被新代码读成坏数据。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..contracts.audit import AuditError
from ..contracts.sdl import SDLProject
from ..layer2_sdl.sdl_migrate import migrate_sdl
from ..layer2_sdl.sdl_validator import validate_sdl

PROJECT_FILENAME = "project.bdproj"


class ProjectError(RuntimeError):
    """项目文件不可用。消息里给出可执行的下一步。"""


@dataclass
class LoadedProject:
    sdl: SDLProject
    path: Path
    notes: List[str] = field(default_factory=list)
    findings: List[AuditError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(item.is_error for item in self.findings)

    def summary(self) -> Dict[str, Any]:
        return {"path": str(self.path), "name": self.sdl.name,
                "version": self.sdl.version,
                "scenes": len(self.sdl.scenes),
                "shots": len(self.sdl.shots),
                "characters": len(self.sdl.characters),
                "total_frames": self.sdl.total_frames,
                "notes": list(self.notes),
                "errors": [item.to_dict() for item in self.findings
                           if item.is_error],
                "warnings": [item.to_dict() for item in self.findings
                             if not item.is_error]}


def project_file(directory: Union[str, Path]) -> Path:
    return Path(directory) / PROJECT_FILENAME


def project_exists(directory: Union[str, Path]) -> bool:
    return project_file(directory).exists()


def validation_report(loaded: "LoadedProject") -> Dict[str, Any]:
    """把一次加载的校验结果整理成**报告**（不是闸门）。

    分两份：``ok`` 直说校验过没过，``errors`` / ``warnings`` 原样列出每条
    finding，``rules`` 是被触发的规则 id。

    为什么要单独抽出来（2026-10-03）：校验的职责是**如实报告**，而"要不要
    继续"是调用方的策略。真跑收尾的 `project.bdproj` 里带着 26 条 S6，
    旧写法让 `rebuild_project` 直接失败——"改一镜、重出一镜"这条工作流于是
    对**真实运行**（恰恰是最需要修的那些跑）是断的。审查与执行分开之后，
    报告仍然一条不少，闸门交给了真正该管交付的那一步。
    """
    findings = [item.to_dict() for item in loaded.findings]
    errors = [item for item in findings if item.get("severity") == "error"]
    return {
        "ok": bool(loaded.ok),
        "path": str(loaded.path),
        "notes": list(loaded.notes),
        "errors": errors,
        "warnings": [item for item in findings
                     if item.get("severity") != "error"],
        "rules": sorted({str(item.get("rule") or "") for item in errors}),
    }


def save_project(directory: Union[str, Path], sdl: SDLProject, *,
                 extra: Optional[Dict[str, Any]] = None) -> Path:
    """把 SDL 写入 ``project.bdproj``，返回文件路径。"""
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = dict(sdl.to_dict())
    payload["saved_at"] = datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")
    if extra:
        payload.update(extra)
    path = project_file(target_dir)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def load_project(directory: Union[str, Path], *,
                 validate: bool = True) -> LoadedProject:
    """读取项目：迁移 → 反序列化 → 校验。"""
    path = project_file(directory)
    if not path.exists():
        raise ProjectError(f"找不到项目文件：{path}。请先运行一次生成，"
                           f"或检查 --project 目录是否正确")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError, OSError) as exc:
        # v1.4 X2：坏数据（非法 JSON、错误编码、读不了）都必须变成可读的
        # ProjectError，而不是把底层异常原样抛给调用方。
        raise ProjectError(f"项目文件无法读取或不是合法 JSON：{exc}") from exc

    payload, notes = migrate_sdl(raw)
    sdl = SDLProject.from_dict(payload)
    findings = validate_sdl(sdl) if validate else []
    return LoadedProject(sdl=sdl, path=path, notes=notes, findings=findings)

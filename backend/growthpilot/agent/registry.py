"""Typed tool registry for the marketing agent.

Each tool declares a Pydantic input schema, a permission level and a description. The agent can only act
through these tools: there is no shell, SQL or free-form network access. Tools that use fixtures instead of a
real source return ``is_mock=True`` and the UI labels them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AgentRun


class Permission(StrEnum):
    READ = "read"  # read workspace data
    RESEARCH = "research"  # fetch public external data (live mode only)
    DRAFT = "draft"  # create/modify drafts, campaigns, hypotheses, findings
    APPROVAL = "approval"  # submit items to the human approval queue
    PUBLISH = "publish"  # schedule/publish — only items a human approved


class Role(StrEnum):
    """Specialist roles. The orchestrator (planner) delegates to them; each tool belongs to one."""

    ORCHESTRATOR = "orchestrator"
    RESEARCH = "research"
    STRATEGY = "strategy"
    CREATIVE = "creative"
    VERIFICATION = "verification"
    DISTRIBUTION = "distribution"
    ANALYST = "analyst"


ROLE_LABELS = {
    Role.ORCHESTRATOR: "Orchestrator", Role.RESEARCH: "Research Agent", Role.STRATEGY: "Strategy Agent",
    Role.CREATIVE: "Creative Agent", Role.VERIFICATION: "Brand & Product Verification Agent",
    Role.DISTRIBUTION: "Distribution Agent", Role.ANALYST: "Performance Analyst Agent",
}


class Effect(StrEnum):
    """What a tool can change. Consequential effects are gated by approvals in the services they call."""

    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"  # creates/edits records or files in this workspace
    COST = "cost"  # may call a paid provider (LLM, search, image generation)
    EXTERNAL_READ = "external_read"  # reads a third-party service
    EXTERNAL_WRITE = "external_write"  # changes state at a third party (not public)
    PUBLIC_PUBLISH = "public_publish"  # posts publicly — only human-approved versions


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class ToolBlocked(RuntimeError):
    """A missing credential/permission/data means the tool can't run. Planner should branch."""

    def __init__(self, message: str, *, blocker: str = ""):
        super().__init__(message)
        self.blocker = blocker or message


@dataclass
class ToolResult:
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    is_mock: bool = False
    tokens: int = 0


@dataclass
class ToolContext:
    db: Session
    run: AgentRun
    workspace_id: int
    brand_id: int | None
    settings: Settings
    user_role: str

    @property
    def state(self) -> dict:
        return self.run.state

    def remember(self, key: str, value: Any) -> None:
        st = dict(self.run.state or {})
        st[key] = value
        self.run.state = st  # reassign so SQLAlchemy sees the JSON change

    def remember_ids(self, key: str, ids: list[int]) -> None:
        cur = list((self.run.state or {}).get(key, []))
        self.remember(key, cur + [i for i in ids if i not in cur])


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[ToolInput]
    permission: Permission
    fn: Callable[[ToolContext, Any], ToolResult]
    #: Short note on what is real vs. mocked, shown in the UI.
    implementation: str = "real"
    role: Role = Role.ORCHESTRATOR
    effects: tuple[Effect, ...] = (Effect.READ_ONLY,)

    def schema(self) -> dict:
        s = self.input_model.model_json_schema()
        s.pop("title", None)
        return s

    def as_anthropic_tool(self) -> dict:
        tag = f"[{ROLE_LABELS[self.role]} · {', '.join(e.value for e in self.effects)}] "
        return {"name": self.name, "description": tag + self.description, "input_schema": self.schema()}

    def info(self) -> dict:
        return {"name": self.name, "description": self.description, "permission": self.permission.value,
                "implementation": self.implementation, "role": self.role.value, "role_label": ROLE_LABELS[self.role],
                "effects": [e.value for e in self.effects], "input_schema": self.schema()}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, input_model: type[ToolInput], permission: Permission,
         implementation: str = "real", *, role: Role = Role.ORCHESTRATOR,
         effects: tuple[Effect, ...] = (Effect.READ_ONLY,)):
    def deco(fn):
        REGISTRY[name] = Tool(name, description, input_model, permission, fn, implementation, role, effects)
        return fn

    return deco


def get_tool(name: str) -> Tool:
    if name not in REGISTRY:
        raise ToolError(f"Unknown tool {name!r}.")
    return REGISTRY[name]

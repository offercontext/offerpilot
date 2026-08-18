from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict, cast

from offerpilot.ai.tool_runtime.context import ToolCapability, ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import BindingTarget, JSONValue, ToolSpec
from offerpilot.ai.tool_specs.common import (
    NOT_FOUND_EXCEPTION_MAP,
    ToolRecordNotFound,
    compact_json,
    decode_mapping,
    integer,
    jd_analysis_json,
    optional_integer,
    provider_contract,
)


class JDArgs(TypedDict, total=False):
    id: int
    application_id: int


def _decode(values: Mapping[str, JSONValue]) -> JDArgs:
    return cast(JDArgs, decode_mapping(values))


def _application_binding(args: JDArgs, context: ToolExecutionContext) -> BindingTarget:
    del context
    identity = args.get("application_id")
    return BindingTarget("application", identity, identity is not None)


def _analysis_binding(args: JDArgs, context: ToolExecutionContext) -> BindingTarget:
    analysis_id = args.get("id")
    analysis = context.jd_analyses.get(analysis_id) if analysis_id is not None else None
    identity = analysis.application_id if analysis is not None else None
    return BindingTarget("application", identity, identity is not None)


def _list(args: JDArgs, context: ToolExecutionContext) -> list[dict[str, Any]]:
    return [jd_analysis_json(row) for row in context.jd_analyses.list(application_id=optional_integer(args, "application_id"))]


def _get(args: JDArgs, context: ToolExecutionContext) -> dict[str, Any]:
    analysis = context.jd_analyses.get(integer(args, "id", "get_jd_analysis"))
    if analysis is None:
        raise ToolRecordNotFound("jd analysis not found")
    return jd_analysis_json(analysis)


def jd_analysis_specs() -> tuple[ToolSpec[Any, Any], ...]:
    read = frozenset({ToolCapability.JD_ANALYSES_READ})
    return (
        ToolSpec(contract=provider_contract("list_jd_analyses", "List saved JD analyses. Optionally filter by application id.", {"type": "object", "properties": {"application_id": {"type": "integer"}}}), kind="read", decoder=_decode, executor=_list, required_capabilities=read, binding_resolvers=(_application_binding,), success_renderer=compact_json),
        ToolSpec(contract=provider_contract("get_jd_analysis", "Get one saved JD analysis by id.", {"type": "object", "properties": {"id": {"type": "integer", "description": "JD analysis id."}}, "required": ["id"]}), kind="read", decoder=_decode, executor=_get, required_capabilities=read, binding_resolvers=(_analysis_binding,), declared_failure_categories=frozenset({"not_found"}), exception_map=NOT_FOUND_EXCEPTION_MAP, success_renderer=compact_json),
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from offerpilot.ai.tool_runtime.contracts import ProviderToolContract
from offerpilot.ai.tool_specs.catalog import MODEL_TOOL_NAMES
from offerpilot.context_projector.contracts import ProjectionError, canonical_json, sha256_hex

SELECTOR_VERSION = "tool-surface-selector-v1"

_DOMAIN_TOOLS: dict[str, frozenset[str]] = {
    "applications": frozenset(
        {"list_applications", "get_application", "create_application", "update_application_status"}
    ),
    "events": frozenset(
        {
            "list_application_events",
            "get_application_event",
            "create_application_event",
            "update_application_event",
            "delete_application_event",
        }
    ),
    "notes": frozenset({"list_notes", "add_note", "update_note", "delete_note"}),
    "offers": frozenset(
        {"list_offers", "get_offer", "compare_offers", "update_offer", "save_offer_assessment"}
    ),
    "resumes": frozenset(
        {
            "list_resumes",
            "get_resume",
            "resume_update_career_intent",
            "resume_rewrite_highlight",
            "list_resume_matches",
        }
    ),
    "jd": frozenset({"list_jd_analyses", "get_jd_analysis"}),
}

_DEPENDENCIES: dict[str, frozenset[str]] = {
    "get_application": frozenset({"list_applications"}),
    "update_application_status": frozenset({"get_application"}),
    "get_application_event": frozenset({"list_application_events"}),
    "update_application_event": frozenset({"get_application_event"}),
    "delete_application_event": frozenset({"get_application_event"}),
    "update_note": frozenset({"list_notes"}),
    "delete_note": frozenset({"list_notes"}),
    "get_offer": frozenset({"list_offers"}),
    "compare_offers": frozenset({"list_offers", "get_offer"}),
    "update_offer": frozenset({"get_offer"}),
    "save_offer_assessment": frozenset({"get_offer"}),
    "get_resume": frozenset({"list_resumes"}),
    "resume_update_career_intent": frozenset({"get_resume"}),
    "resume_rewrite_highlight": frozenset({"get_resume"}),
    "list_resume_matches": frozenset({"list_resumes"}),
    "get_jd_analysis": frozenset({"list_jd_analyses"}),
}

_LEXICAL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "applications",
        ("投递", "申请", "application", "company", "岗位", "职位", "改成 offer"),
    ),
    ("events", ("日程", "面试时间", "笔试", "deadline", "event", "提醒")),
    ("notes", ("复盘", "笔记", "note", "记录")),
    ("offers", ("offer", "薪资", "谈薪", "待遇", "比较")),
    ("resumes", ("简历", "resume", "经历", "求职意向")),
    ("jd", ("jd", "职位描述", "job description", "匹配分析")),
)

_PAGE_DOMAINS = {
    "workspace": frozenset(),
    "applications": frozenset({"applications"}),
    "application": frozenset({"applications", "events", "notes", "offers", "resumes", "jd"}),
    "calendar": frozenset({"events", "applications"}),
    "notes": frozenset({"notes", "applications"}),
    "offers": frozenset({"offers", "applications"}),
    "resumes": frozenset({"resumes", "jd"}),
}
_ATTACHMENT_DOMAINS = {
    "resume": frozenset({"resumes"}),
    "job_description": frozenset({"jd", "applications"}),
    "image": frozenset(),
    "document": frozenset(),
}


@dataclass(frozen=True)
class ToolSelectionSignals:
    page_kind: str = "workspace"
    attachment_kinds: tuple[str, ...] = ()
    current_request: str = ""
    trusted_domains: tuple[str, ...] = ()
    version: str = SELECTOR_VERSION


@dataclass(frozen=True)
class ToolSelection:
    tools: tuple[ProviderToolContract, ...]
    names: tuple[str, ...]
    envelope_fingerprint: str
    fallback_all: bool
    domains: tuple[str, ...]


def _dependency_closure(names: set[str]) -> set[str]:
    pending = list(names)
    while pending:
        name = pending.pop()
        for dependency in _DEPENDENCIES.get(name, ()):
            if dependency not in MODEL_TOOL_NAMES:
                raise ProjectionError("tool_dependency_missing")
            if dependency not in names:
                names.add(dependency)
                pending.append(dependency)
    return names


def select_tools(
    catalog: Iterable[ProviderToolContract],
    signals: ToolSelectionSignals,
) -> ToolSelection:
    if signals.version != SELECTOR_VERSION:
        raise ProjectionError("unsupported_selector_version")
    contracts = tuple(catalog)
    names = tuple(contract.name for contract in contracts)
    if names != MODEL_TOOL_NAMES or len(set(names)) != len(names):
        raise ProjectionError("typed_catalog_drift")
    if signals.page_kind not in _PAGE_DOMAINS:
        raise ProjectionError("unknown_page_kind")
    if any(kind not in _ATTACHMENT_DOMAINS for kind in signals.attachment_kinds):
        raise ProjectionError("unknown_attachment_kind")
    if any(domain not in _DOMAIN_TOOLS for domain in signals.trusted_domains):
        raise ProjectionError("unknown_trusted_domain")

    domains = set(signals.trusted_domains)
    domains.update(_PAGE_DOMAINS[signals.page_kind])
    for kind in signals.attachment_kinds:
        domains.update(_ATTACHMENT_DOMAINS[kind])
    normalized_request = signals.current_request.casefold()[:16_384]
    for domain, terms in _LEXICAL_RULES:
        if any(term in normalized_request for term in terms):
            domains.add(domain)

    fallback_all = not domains
    selected_names: set[str]
    if fallback_all:
        selected_names = set(MODEL_TOOL_NAMES)
    else:
        selected_names = set()
        for domain in domains:
            selected_names.update(_DOMAIN_TOOLS[domain])
        _dependency_closure(selected_names)
    selected = tuple(contract for contract in contracts if contract.name in selected_names)
    ordered_names = tuple(contract.name for contract in selected)
    if not selected or not set(ordered_names).issubset(MODEL_TOOL_NAMES):
        raise ProjectionError("invalid_tool_surface")
    envelopes = [dict(contract.payload) for contract in selected]
    return ToolSelection(
        tools=selected,
        names=ordered_names,
        envelope_fingerprint=sha256_hex(canonical_json(envelopes)),
        fallback_all=fallback_all,
        domains=tuple(sorted(domains)),
    )

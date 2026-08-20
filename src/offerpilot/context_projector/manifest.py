from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from offerpilot.context_projector.contracts import CONTRIBUTOR_ORDER, RuntimeSurfaceAudit
from offerpilot.ai.tool_specs.catalog import MODEL_TOOL_NAMES

MANIFEST_SCHEMA_VERSION = 2
MANIFEST_BYTE_CAP = 65_536
_HEX64 = re.compile(r"[0-9a-f]{64}")
_SAFE_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_STATUSES = {"ready", "not_applicable", "disabled", "unavailable"}
MANIFEST_SIGNAL_VALUES = (
    "trusted_page",
    "trusted_attachment",
    "lexical_application",
    "lexical_event",
    "lexical_note",
    "lexical_offer",
    "lexical_resume",
    "lexical_jd",
    "fallback_all_tools",
    "structural_workspace",
    "structural_application",
    "structural_calendar",
    "structural_notes",
    "structural_offers",
    "structural_resumes",
    "attachment_resume",
    "attachment_job_description",
    "attachment_image",
    "attachment_document",
    "scope_workspace",
    "scope_global",
    "scope_application",
    "scope_mode",
    "control_pending",
    "control_confirmation",
    "control_read_chain",
    "control_delivery",
    "history_recent",
    "history_relevant",
    "history_orphan_compat",
    "catalog_dependency_closure",
    "catalog_domain_union",
)
_SIGNALS = frozenset(MANIFEST_SIGNAL_VALUES)


class ManifestV2ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedSurfaceManifestV2:
    manifest_json: str
    manifest_digest: str
    fingerprint_key_id: str


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity(secret: bytes, domain: bytes, value: str) -> str:
    return hmac.new(secret, domain + b"\0" + value.encode("utf-8"), hashlib.sha256).hexdigest()


def prepare_surface_manifest_v2(
    audit: RuntimeSurfaceAudit,
    *,
    key_id: str,
    secret: bytes,
    provider_identities: tuple[str, ...],
    signals: tuple[str, ...] = (),
) -> PreparedSurfaceManifestV2:
    """Failing helper; callers/recorders must catch all failures (journal is fail-open)."""
    sources = [
        {
            "source_hmac": _identity(
                secret,
                b"offerpilot-surface-source-v2",
                f"{source.kind}:{source.revision_identity}",
            ),
            "content_revision_fingerprint": source.content_revision_fingerprint,
            "chunks": [
                {
                    "path_hmac": _identity(secret, b"offerpilot-surface-chunk-v2", chunk.path),
                    "ordinal": chunk.ordinal,
                    "total": chunk.total,
                    "truncated": chunk.truncated,
                    "original_bytes": chunk.original_bytes,
                    "original_codepoints": chunk.original_codepoints,
                }
                for chunk in source.chunks
            ],
        }
        for source in audit.source_records
    ]
    if not sources:
        sources = [
            {
                "source_hmac": _identity(
                    secret, b"offerpilot-surface-source-v2", f"{index}:{fingerprint}"
                ),
                "content_revision_fingerprint": fingerprint,
                "chunks": [],
            }
            for index, fingerprint in enumerate(audit.source_fingerprints)
        ]
    effective_signals = signals or audit.signals
    manifest = {
        "manifest_schema_version": 2,
        "budget_policy_version": audit.budget_policy_version,
        "providers": [
            _identity(secret, b"offerpilot-surface-provider-v2", item)
            for item in provider_identities
        ],
        "contributors": [
            {"name": name, "status": status} for name, status in audit.contributor_statuses
        ],
        "history_groups": [
            _identity(secret, b"offerpilot-surface-history-v2", item)
            for item in audit.selected_history_group_ids
        ],
        "tools": list(audit.selected_tool_names),
        "sources": sources,
        "signals": list(effective_signals),
        "counts": {
            "estimated_input_units": audit.estimated_input_units,
            "canonical_message_bytes": audit.canonical_message_bytes,
            "canonical_tool_bytes": audit.canonical_tool_bytes,
        },
        "truncated": audit.truncated,
        "fingerprint_key_id": key_id,
    }
    rendered = _canonical(manifest)
    validate_surface_manifest_v2(rendered)
    return PreparedSurfaceManifestV2(
        rendered,
        hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        key_id,
    )


def validate_surface_manifest_v2(value: str) -> dict[str, Any]:
    if len(value.encode("utf-8")) > MANIFEST_BYTE_CAP:
        raise ManifestV2ValidationError("manifest exceeds 64 KiB")
    try:
        manifest = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        raise ManifestV2ValidationError("invalid manifest JSON") from None
    required = {
        "manifest_schema_version",
        "budget_policy_version",
        "providers",
        "contributors",
        "history_groups",
        "tools",
        "sources",
        "signals",
        "counts",
        "truncated",
        "fingerprint_key_id",
    }
    if type(manifest) is not dict or set(manifest) != required or _canonical(manifest) != value:
        raise ManifestV2ValidationError("invalid manifest shape or canonical form")
    if manifest["manifest_schema_version"] != 2:
        raise ManifestV2ValidationError("invalid manifest version")
    if manifest["budget_policy_version"] != "model-surface-budget-v1":
        raise ManifestV2ValidationError("invalid budget policy")
    _hash_array(manifest["providers"], 8)
    _hash_array(manifest["history_groups"], 32)
    providers = manifest["providers"]
    if not providers:
        raise ManifestV2ValidationError("empty provider chain")
    contributors = manifest["contributors"]
    if type(contributors) is not list or len(contributors) != 10:
        raise ManifestV2ValidationError("invalid contributors")
    for item in contributors:
        if (
            type(item) is not dict
            or set(item) != {"name", "status"}
            or type(item["name"]) is not str
            or _SAFE_NAME.fullmatch(item["name"]) is None
            or type(item["status"]) is not str
            or item["status"] not in _STATUSES
        ):
            raise ManifestV2ValidationError("invalid contributor")
    if tuple(item["name"] for item in contributors) != CONTRIBUTOR_ORDER:
        raise ManifestV2ValidationError("invalid contributor order")
    tools = manifest["tools"]
    if type(tools) is not list or len(tools) > 25:
        raise ManifestV2ValidationError("invalid tools")
    if any(type(item) is not str or _SAFE_NAME.fullmatch(item) is None for item in tools):
        raise ManifestV2ValidationError("invalid tool")
    if len(set(tools)) != len(tools):
        raise ManifestV2ValidationError("invalid tools")
    if any(item not in MODEL_TOOL_NAMES for item in tools):
        raise ManifestV2ValidationError("unapproved tool")
    signals = manifest["signals"]
    if type(signals) is not list or len(signals) > 32:
        raise ManifestV2ValidationError("invalid signals")
    if any(type(signal) is not str for signal in signals):
        raise ManifestV2ValidationError("invalid signal")
    if len(set(signals)) != len(signals):
        raise ManifestV2ValidationError("invalid signals")
    if any(signal not in _SIGNALS for signal in signals):
        raise ManifestV2ValidationError("invalid signal")
    sources = manifest["sources"]
    if type(sources) is not list or len(sources) > 8:
        raise ManifestV2ValidationError("invalid sources")
    total_chunks = 0
    for source in sources:
        if type(source) is not dict or set(source) != {
            "source_hmac",
            "content_revision_fingerprint",
            "chunks",
        }:
            raise ManifestV2ValidationError("invalid source")
        if not _is_hex64(source["source_hmac"]) or not _is_hex64(
            source["content_revision_fingerprint"]
        ):
            raise ManifestV2ValidationError("invalid source fingerprint")
        chunks = source["chunks"]
        if type(chunks) is not list or len(chunks) > 32:
            raise ManifestV2ValidationError("invalid chunks")
        total_chunks += len(chunks)
        seen_ordinals: set[int] = set()
        for chunk in chunks:
            if type(chunk) is not dict or set(chunk) != {
                "path_hmac",
                "ordinal",
                "total",
                "truncated",
                "original_bytes",
                "original_codepoints",
            }:
                raise ManifestV2ValidationError("invalid chunk")
            if not _is_hex64(chunk["path_hmac"]):
                raise ManifestV2ValidationError("invalid chunk identity")
            if (
                any(
                    type(chunk[key]) is not int or chunk[key] < 0
                    for key in ("ordinal", "total", "original_bytes", "original_codepoints")
                )
                or type(chunk["truncated"]) is not bool
            ):
                raise ManifestV2ValidationError("invalid chunk counts")
            if (
                chunk["ordinal"] < 1
                or chunk["total"] != len(chunks)
                or chunk["ordinal"] > chunk["total"]
            ):
                raise ManifestV2ValidationError("invalid chunk ordinal")
            seen_ordinals.add(chunk["ordinal"])
        if seen_ordinals != set(range(1, len(chunks) + 1)):
            raise ManifestV2ValidationError("invalid chunk ordinal")
    if total_chunks > 64:
        raise ManifestV2ValidationError("too many chunks")
    counts = manifest["counts"]
    if type(counts) is not dict or set(counts) != {
        "estimated_input_units",
        "canonical_message_bytes",
        "canonical_tool_bytes",
    }:
        raise ManifestV2ValidationError("invalid counts")
    if any(type(item) is not int or item < 0 for item in counts.values()):
        raise ManifestV2ValidationError("invalid count")
    if type(manifest["truncated"]) is not bool:
        raise ManifestV2ValidationError("invalid truncated flag")
    try:
        key_id = str(UUID(manifest["fingerprint_key_id"]))
    except (TypeError, ValueError, AttributeError):
        raise ManifestV2ValidationError("invalid key id") from None
    if key_id != manifest["fingerprint_key_id"]:
        raise ManifestV2ValidationError("invalid key id")
    if "logical_input_fingerprint" in manifest:
        raise ManifestV2ValidationError("logical fingerprint must not be duplicated")
    return manifest


def _hash_array(value: object, maximum: int) -> None:
    if type(value) is not list or len(value) > maximum:
        raise ManifestV2ValidationError("invalid identity array")
    if any(not _is_hex64(item) for item in value):
        raise ManifestV2ValidationError("invalid identity")
    if len(set(value)) != len(value):
        raise ManifestV2ValidationError("duplicate identity")


def _is_hex64(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None

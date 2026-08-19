from __future__ import annotations

from dataclasses import dataclass, field

from offerpilot.ai.types import Assistant
from offerpilot.context_projector.contracts import FrozenModelSurface, ProjectionError


@dataclass(frozen=True)
class ModelCallSurfaceBinding:
    model_call_id: str
    runtime_surface_fingerprint: str
    exposed_tool_names: frozenset[str]
    provider_candidate_count: int

    @classmethod
    def from_surface(cls, surface: FrozenModelSurface) -> ModelCallSurfaceBinding:
        return cls(
            surface.model_call_id,
            surface.runtime_surface_fingerprint,
            frozenset(tool.name for tool in surface.tools),
            surface.provider_candidate_count,
        )

    def validate_response(self, response: BoundProviderResponse) -> Assistant:
        assistant = self.validate_provenance(response)
        for call in assistant.tool_calls:
            if call.name not in self.exposed_tool_names:
                raise ProjectionError("unknown_tool")
        return assistant

    def validate_provenance(self, response: BoundProviderResponse) -> Assistant:
        if response.model_call_id != self.model_call_id:
            raise ProjectionError("provider_response_model_call_mismatch")
        if response.runtime_surface_fingerprint != self.runtime_surface_fingerprint:
            raise ProjectionError("provider_response_surface_mismatch")
        if response.candidate_ordinal >= self.provider_candidate_count:
            raise ProjectionError("provider_response_candidate_mismatch")
        return response.response


@dataclass(frozen=True)
class BoundProviderResponse:
    model_call_id: str
    candidate_ordinal: int
    provider_attempt_id: str
    runtime_surface_fingerprint: str
    response: Assistant = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not self.model_call_id
            or self.candidate_ordinal < 0
            or not self.provider_attempt_id
            or len(self.runtime_surface_fingerprint) != 64
        ):
            raise ProjectionError("invalid_bound_provider_response")

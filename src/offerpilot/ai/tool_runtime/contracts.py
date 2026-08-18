from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, NoReturn, Protocol, SupportsIndex, TypeAlias, TypeVar


JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)
ToolKind: TypeAlias = Literal["read", "write"]
ConfirmationPolicy: TypeAlias = Literal["none", "required"]
FailureCategory: TypeAlias = Literal[
    "validation_error",
    "permission_denied",
    "confirmation_rejected",
    "stale_state",
    "conflict",
    "not_found",
    "provider_error",
    "internal_error",
]
BindingStatus: TypeAlias = Literal["matched", "mismatched", "unbound", "unavailable"]

ArgsT = TypeVar("ArgsT")
ResultT = TypeVar("ResultT")


class TransientToolRuntimeValue:
    """A request-scoped value that must never enter a checkpoint or generic payload."""

    __slots__ = ()

    @staticmethod
    def _serialization_error() -> TypeError:
        return TypeError("transient tool runtime value cannot be serialized")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise self._serialization_error()

    def __getstate__(self) -> NoReturn:
        raise self._serialization_error()

    def to_json(self) -> NoReturn:
        raise self._serialization_error()


@dataclass(frozen=True)
class ProviderToolContract:
    payload: Mapping[str, JSONValue] = field(repr=False)
    name: str
    description: str
    parameters: Mapping[str, JSONValue] = field(repr=False)

    def __post_init__(self) -> None:
        function = self.payload.get("function")
        if self.payload.get("type") != "function" or not isinstance(function, Mapping):
            raise ValueError("invalid provider tool envelope")
        if function.get("name") != self.name:
            raise ValueError("provider tool name mismatch")
        if function.get("description") != self.description:
            raise ValueError("provider tool description mismatch")
        if function.get("parameters") != self.parameters:
            raise ValueError("provider tool parameters mismatch")


@dataclass(frozen=True)
class BindingAudit:
    status: BindingStatus
    target_count: int

    def __post_init__(self) -> None:
        if self.target_count < 0:
            raise ValueError("binding target_count must be non-negative")


@dataclass(frozen=True)
class ToolFailure(TransientToolRuntimeValue):
    category: FailureCategory
    code: str
    compatibility_detail: str = field(default="", repr=False, compare=False)


@dataclass(frozen=True)
class ToolSuccess(TransientToolRuntimeValue, Generic[ResultT]):
    result: ResultT = field(repr=False)


ToolOutcome: TypeAlias = ToolSuccess[ResultT] | ToolFailure


class ToolExecutionContextProtocol(Protocol):
    capabilities: frozenset[str]
    repositories: object


@dataclass(frozen=True)
class ToolExceptionMapping:
    exception_type: type[Exception]
    category: FailureCategory
    code: str
    compatibility_detail: Callable[[Exception], str] | None = field(
        default=None,
        repr=False,
        compare=False,
    )


ToolDecoder: TypeAlias = Callable[[Mapping[str, JSONValue]], ArgsT]
ToolCheck: TypeAlias = Callable[[ArgsT, ToolExecutionContextProtocol], ToolFailure | None]
ToolExecutor: TypeAlias = Callable[[ArgsT, ToolExecutionContextProtocol], ResultT]
BindingResolver: TypeAlias = Callable[[ArgsT, ToolExecutionContextProtocol], object]


@dataclass(frozen=True)
class ToolSpec(Generic[ArgsT, ResultT]):
    contract: ProviderToolContract
    kind: ToolKind
    decoder: ToolDecoder[ArgsT] = field(repr=False, compare=False)
    executor: ToolExecutor[ArgsT, ResultT] = field(repr=False, compare=False)
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    binding_resolvers: tuple[BindingResolver[ArgsT], ...] = field(default_factory=tuple)
    confirmation_policy: ConfirmationPolicy = "none"
    editable_fields: tuple[Mapping[str, JSONValue], ...] = field(default_factory=tuple)
    preflight: ToolCheck[ArgsT] | None = field(default=None, repr=False, compare=False)
    mutable_validator: ToolCheck[ArgsT] | None = field(default=None, repr=False, compare=False)
    declared_failure_categories: frozenset[FailureCategory] = field(default_factory=frozenset)
    exception_map: tuple[ToolExceptionMapping, ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        return self.contract.name


@dataclass(frozen=True)
class PreparedToolCall(TransientToolRuntimeValue, Generic[ArgsT, ResultT]):
    tool_call_id: str
    spec: ToolSpec[ArgsT, ResultT] = field(repr=False)
    arguments: Mapping[str, JSONValue] = field(repr=False)
    typed_args: ArgsT = field(repr=False)
    arguments_digest: str
    binding: BindingAudit


@dataclass(frozen=True)
class ConfirmationRequired(TransientToolRuntimeValue, Generic[ArgsT, ResultT]):
    prepared: PreparedToolCall[ArgsT, ResultT] = field(repr=False)


@dataclass(frozen=True)
class ReadyToExecute(TransientToolRuntimeValue, Generic[ArgsT, ResultT]):
    prepared: PreparedToolCall[ArgsT, ResultT] = field(repr=False)


PreparedCallResult: TypeAlias = (
    ConfirmationRequired[ArgsT, ResultT] | ReadyToExecute[ArgsT, ResultT] | ToolFailure
)


@dataclass(frozen=True)
class ExecutionAuthorization(TransientToolRuntimeValue):
    pending_identity: object = field(repr=False, compare=False)
    pending_action_revision: int
    tool_call_id: str
    tool_name: str
    arguments_digest: str


@dataclass(frozen=True)
class ToolExecutionRecord(TransientToolRuntimeValue, Generic[ArgsT, ResultT]):
    prepared: PreparedToolCall[ArgsT, ResultT] = field(repr=False)
    outcome: ToolSuccess[ResultT] | ToolFailure = field(repr=False)
    execution_started: bool


def heterogeneous_spec(spec: ToolSpec[ArgsT, ResultT]) -> ToolSpec[Any, Any]:
    """Confine heterogeneous Catalog erasure to one reviewed boundary."""

    return spec

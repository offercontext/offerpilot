from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from offerpilot.ai.provider_boundaries import (
    NON_AGENT_PROVIDER_CALL_MANIFEST,
    RAW_PROVIDER_BOUNDARIES,
)

ROOT = Path(__file__).resolve().parents[1] / "src" / "offerpilot"


def _functions(path: Path) -> dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef] = {}
    class_name = ""

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            nonlocal class_name
            previous, class_name = class_name, node.name
            self.generic_visit(node)
            class_name = previous

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            result[(class_name, node.name)] = node
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    return result


def test_fixed_non_agent_manifest_has_13_functions_and_18_calls() -> None:
    assert len(NON_AGENT_PROVIDER_CALL_MANIFEST) == 13
    assert sum(count for _, _, count in NON_AGENT_PROVIDER_CALL_MANIFEST) == 18
    for relative, function_name, expected_calls in NON_AGENT_PROVIDER_CALL_MANIFEST:
        node = _functions(ROOT.parent / relative)[("", function_name)]
        actual = sum(
            isinstance(call.func, ast.Attribute)
            and call.func.attr in {"complete", "stream_complete"}
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )
        assert actual == expected_calls, (relative, function_name)


def test_raw_provider_boundary_manifest_resolves_exactly_five_functions() -> None:
    assert len(RAW_PROVIDER_BOUNDARIES) == 5
    for relative, class_name, function_name in RAW_PROVIDER_BOUNDARIES:
        assert (class_name, function_name) in _functions(ROOT.parent / relative)


def test_litellm_imports_are_confined_and_cli_uses_knowledge_factory() -> None:
    imports: list[str] = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(alias.name == "litellm" for alias in node.names):
                imports.append(path.relative_to(ROOT.parent).as_posix())
            if isinstance(node, ast.ImportFrom) and node.module == "litellm":
                imports.append(path.relative_to(ROOT.parent).as_posix())
    assert Counter(imports) == Counter(
        {"offerpilot/ai/client.py": 1, "offerpilot/knowledge/provider.py": 1}
    )
    cli = (ROOT / "cli.py").read_text(encoding="utf-8")
    cli_tree = ast.parse(cli)
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "litellm"
        for node in ast.walk(cli_tree)
    )
    assert "build_knowledge_brief_provider_client" in cli


def test_provider_boundary_functions_have_no_dynamic_import_or_generic_http_call() -> None:
    forbidden_call_names = {"__import__", "import_module"}
    for relative, class_name, function_name in RAW_PROVIDER_BOUNDARIES:
        node = _functions(ROOT.parent / relative)[(class_name, function_name)]
        for call in (item for item in ast.walk(node) if isinstance(item, ast.Call)):
            if isinstance(call.func, ast.Name):
                assert call.func.id not in forbidden_call_names
            elif isinstance(call.func, ast.Attribute):
                assert call.func.attr not in forbidden_call_names
                if isinstance(call.func.value, ast.Name) and call.func.value.id in {
                    "httpx",
                    "requests",
                    "aiohttp",
                }:
                    assert call.func.attr not in {"request", "post", "get"}

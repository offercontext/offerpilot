from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_python_runtime_not_go_builder():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "python:" in dockerfile
    assert "uv sync" in dockerfile
    assert "COPY --from=web /web/dist" in dockerfile
    assert "go build" not in dockerfile
    assert "golang:" not in dockerfile
    assert 'ENTRYPOINT ["oc"]' in dockerfile


def test_install_script_installs_python_tool_not_go_binary():
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert "uv tool install" in script
    assert "requires Python 3.10+" in script
    assert "go build" not in script
    assert "Go is required" not in script


def test_readme_describes_python_first_runtime():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "uv sync" in readme
    assert "uv run oc start" in readme
    assert "FastAPI" in readme
    assert "go build" not in readme
    assert "Go 1.22" not in readme


def test_readme_documents_current_v01_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "AGPLv3" in readme
    assert "LiteLLM" in readme
    assert "oc smoke" in readme
    assert "pending -> applied -> written_test -> interview -> offer -> closed" in readme
    assert "runtime_mode" in readme
    assert "auth_enabled" in readme


def test_go_backend_sources_removed_after_python_cutover():
    go_sources = [
        path
        for path in ROOT.rglob("*.go")
        if ".git" not in path.parts
        and ".venv" not in path.parts
        and ".worktrees" not in path.parts
        and "web" not in path.parts
    ]

    assert go_sources == []
    assert not (ROOT / "go.mod").exists()
    assert not (ROOT / "go.sum").exists()

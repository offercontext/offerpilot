# Contributing to OfferPilot

Thanks for helping improve OfferPilot.

## License

OfferPilot is licensed under AGPLv3. By contributing, you agree that your contribution can be distributed under the project's AGPLv3 license.

Before the project broadly accepts external contributions, the maintainers should decide whether a CLA or DCO process is required. This follows ADR-001 so future licensing choices are not blocked by unclear contribution rights.

## Development

Use a feature branch or worktree for changes. Keep commits small and use the repository commit convention:

```text
<type>: AI <subject>
```

Valid types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, and `test`.

## Quality Gates

Run the relevant checks before opening a pull request:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
cd web && npm test
cd web && npm run build
```

For user-facing behavior changes, also run a local smoke check with `uv run oc start`.

# Docker Smoke Automation Plan

## Goal

Make the existing Docker runtime path easy to verify with the same core smoke harness used by local development.

## Steps

1. Add a repository contract test for Docker smoke scripts and the static asset path.
2. Add POSIX shell and PowerShell scripts that build the image and run `oc smoke --static-dir /app/web/dist` inside the container.
3. Document the scripts in the README.
4. Run targeted and full verification.

## Acceptance

- `scripts/docker-smoke.sh` builds and runs the Docker smoke command.
- `scripts/docker-smoke.ps1` provides the Windows equivalent.
- README documents both commands.
- Existing Python and frontend verification remains green.

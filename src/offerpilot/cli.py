from __future__ import annotations

from pathlib import Path
import sys
from typing import Optional

import typer
import uvicorn

from offerpilot.ai.client import ConfiguredAIClient
from offerpilot.ai.workflows import analyze_jd, generate_questions, match_resume
from offerpilot.application_status import APPLICATION_STATUS_IDS, normalize_application_status
from offerpilot.api import create_app
from offerpilot.config import (
    AIProviderProfile,
    Config,
    load_config,
    normalize_runtime_mode,
    resolve_data_dir,
    save_config,
)
from offerpilot.db import session_factory_for_data_dir
from offerpilot.diagnostics import append_log_entry
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.jd import JDAnalysesRepository
from offerpilot.repositories.knowledge import KnowledgeRepository
from offerpilot.repositories.notes import NoteCreate, NotesRepository
from offerpilot.repositories.offers import OfferCreate, OffersRepository
from offerpilot.repositories.questions import QuestionsRepository
from offerpilot.repositories.resumes import ResumeCreate, ResumesRepository
from offerpilot.smoke import run_core_smoke
from offerpilot.skills import SkillRegistryError, register_skill, skills_payload, update_skill

app = typer.Typer(help="OfferPilot - your local job search workbench")
resume_app = typer.Typer(help="Manage resumes")
note_app = typer.Typer(help="Manage interview notes")
offer_app = typer.Typer(help="Manage offers")
question_app = typer.Typer(help="Manage interview questions")
skill_app = typer.Typer(help="Manage trusted skill packages")

app.add_typer(resume_app, name="resume")
app.add_typer(note_app, name="note")
app.add_typer(offer_app, name="offer")
app.add_typer(question_app, name="question")
app.add_typer(skill_app, name="skill")


@app.command()
def add(
    company: str = typer.Option(..., "--company", "-c", help="company name (required)"),
    position: str = typer.Option(..., "--position", help="position/job title (required)"),
    url: str = typer.Option("", "--url", "-u", help="job posting URL"),
    notes: str = typer.Option("", "--notes", "-n", help="notes about this application"),
) -> None:
    repo = _applications_repo()
    created = repo.create(
        ApplicationCreate(
            company_name=company,
            position_name=position,
            job_url=url,
            notes=notes,
            status="applied",
            source="cli",
        )
    )

    typer.echo(f"\nAdded: {created.company_name} - {created.position_name}")
    typer.echo(f"   ID: {created.id}  Status: {created.status}")


@app.command(name="list")
def list_applications(
    status: str = typer.Option(
        "",
        "--status",
        "-s",
        help=f"filter by status ({', '.join(APPLICATION_STATUS_IDS)})",
    ),
) -> None:
    repo = _applications_repo()
    try:
        parsed_status = normalize_application_status(status) if status else ""
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    applications = repo.list(status=parsed_status)
    if not applications:
        typer.echo("\nNo applications found. Use 'oc add' to add one.")
        return

    typer.echo("\nJob Applications")
    typer.echo("-------------------------------------------------------------")
    typer.echo(f"{'ID':<4} {'Company':<20} {'Position':<20} {'Status':<12} {'Applied':<12}")
    typer.echo("-------------------------------------------------------------")
    for item in applications:
        typer.echo(
            f"{str(item.id):<4} {_truncate(item.company_name, 20):<20} "
            f"{_truncate(item.position_name, 20):<20} {item.status:<12} "
            f"{item.applied_at.strftime('%Y-%m-%d'):<12}"
        )
    typer.echo(f"\nTotal: {len(applications)} applications")


@app.command()
def config(
    api_key: Optional[str] = typer.Option(None, "--api-key", help="set API key"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="set base_url"),
    model: Optional[str] = typer.Option(None, "--model", help="set model name"),
    runtime_mode: Optional[str] = typer.Option(None, "--runtime-mode", help="local or server"),
    auth_enabled: Optional[bool] = typer.Option(
        None,
        "--auth/--no-auth",
        help="enable auth guard for server mode",
    ),
    log_level: Optional[str] = typer.Option(None, "--log-level", help="DEBUG, INFO, WARNING, ERROR"),
    auto_approve: Optional[bool] = typer.Option(
        None,
        "--auto-approve/--no-auto-approve",
        help="let the AI assistant run write actions without confirmation",
    ),
) -> None:
    data_dir = resolve_data_dir()
    current = load_config(data_dir)
    next_config = Config(**current.model_dump())
    changed = False

    if api_key is not None:
        next_config.api_key = api_key
        next_config = _sync_active_provider_config(next_config, api_key=api_key)
        changed = True
    if base_url is not None:
        next_config.base_url = base_url
        next_config = _sync_active_provider_config(next_config, base_url=base_url)
        changed = True
    if model is not None:
        next_config.model = model
        next_config = _sync_active_provider_config(next_config, model=model)
        changed = True
    if auto_approve is not None:
        next_config.chat_auto_approve_writes = auto_approve
        changed = True
    if runtime_mode is not None:
        parsed_runtime_mode = normalize_runtime_mode(runtime_mode, next_config.runtime_mode)
        if parsed_runtime_mode != runtime_mode:
            raise typer.BadParameter("--runtime-mode must be local or server")
        next_config.runtime_mode = parsed_runtime_mode
        changed = True
    if auth_enabled is not None:
        next_config.auth_enabled = auth_enabled
        changed = True
    if log_level is not None:
        parsed_level = log_level.upper()
        if parsed_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise typer.BadParameter("--log-level must be DEBUG, INFO, WARNING, or ERROR")
        next_config.log_level = parsed_level
        changed = True

    if changed:
        save_config(data_dir, next_config)
        typer.echo(f"Config saved to {data_dir / 'config.json'}")

    _print_config(data_dir, next_config)


@app.command("analyze")
def analyze_command(
    jd: str = typer.Option("", "--jd", "-j", help="JD text to analyze (use '-' to read stdin)"),
    jd_url: str = typer.Option("", "--jd-url", "-u", help="JD page URL to fetch then analyze"),
    app_id: int = typer.Option(0, "--app", "-a", help="linked application ID"),
) -> None:
    jd_text = _read_dash_stdin(jd)
    if bool(jd_text) == bool(jd_url):
        raise typer.BadParameter("provide exactly one of --jd or --jd-url")
    try:
        result = analyze_jd(
            _build_ai_model(),
            _jd_repo(),
            jd_text=jd_text,
            jd_url=jd_url,
            application_id=app_id if app_id > 0 else None,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    summary = str(result.result.get("summary") or "")
    typer.echo(f"\nJD analysis saved  (id: {result.id}, source: {result.jd_source})")
    if summary:
        typer.echo(f"Summary: {summary}")


@app.command()
def start(
    port: Optional[int] = typer.Option(None, "--port", "-p", help="local server port"),
) -> None:
    data_dir = resolve_data_dir()
    cfg = load_config(data_dir)
    resolved_port = port if port is not None else cfg.local_port
    session_factory_for_data_dir(data_dir)
    append_log_entry(data_dir, "INFO", f"server starting on port {resolved_port}")
    typer.echo(f"OfferPilot running at http://localhost:{resolved_port}")
    uvicorn.run(create_app(data_dir=data_dir), host="127.0.0.1", port=resolved_port)


@app.command()
def smoke(
    static_dir: Optional[Path] = typer.Option(None, "--static-dir", help="built frontend dist directory"),
) -> None:
    report = run_core_smoke(resolve_data_dir(), static_dir=static_dir)
    for step in report.steps:
        typer.echo(f"ok {step.name}: {step.detail}")
    typer.echo("Smoke passed")


@skill_app.command("list")
def skill_list() -> None:
    cfg = load_config(resolve_data_dir())
    payload = skills_payload(cfg)
    packages = payload["packages"]
    if not packages:
        typer.echo("\nNo skill packages registered.")
        return
    typer.echo("\nSkill Packages")
    typer.echo("-------------------------------------------------------------")
    typer.echo(f"{'ID':<24} {'Trusted':<8} {'Enabled':<8} {'State':<8} Source")
    for package in packages:
        state = "loaded" if package["loaded"] else "inactive"
        typer.echo(
            f"{package['id']:<24} {_format_bool(package['trusted']):<8} "
            f"{_format_bool(package['enabled']):<8} {state:<8} {package['source']}"
        )


@skill_app.command("add")
def skill_add(
    skill_id: str = typer.Option(..., "--id", help="stable skill id"),
    label: str = typer.Option("", "--label", help="display label"),
    source: str = typer.Option("", "--source", help="local path, package URL, or registry source"),
    version: str = typer.Option("", "--version", help="skill version"),
) -> None:
    cfg = load_config(resolve_data_dir())
    try:
        next_config = register_skill(
            cfg,
            {
                "id": skill_id,
                "label": label,
                "source": source,
                "version": version,
            },
        )
    except SkillRegistryError as exc:
        raise typer.BadParameter(str(exc)) from exc
    save_config(resolve_data_dir(), next_config)
    typer.echo(f"Skill registered: {skill_id}")


@skill_app.command("trust")
def skill_trust(skill_id: str = typer.Argument(...)) -> None:
    _set_skill_state(skill_id, trusted=True)
    typer.echo(f"Skill trusted: {skill_id}")


@skill_app.command("enable")
def skill_enable(skill_id: str = typer.Argument(...)) -> None:
    _set_skill_state(skill_id, enabled=True)
    typer.echo(f"Skill enabled: {skill_id}")


@skill_app.command("disable")
def skill_disable(skill_id: str = typer.Argument(...)) -> None:
    _set_skill_state(skill_id, enabled=False)
    typer.echo(f"Skill disabled: {skill_id}")


@resume_app.command("add")
def resume_add(
    file: Path = typer.Option(..., "--file", "-f", help="path to resume text/markdown file"),
    name: str = typer.Option("", "--name", "-n", help="optional resume name"),
) -> None:
    text = file.read_text(encoding="utf-8")
    created = _resumes_repo().create(
        ResumeCreate(
            name=name,
            file_path=str(file),
            parsed_data=text,
            parse_status="text-ready",
        )
    )
    typer.echo(f"\nResume saved  (id: {created.id}, name: {created.name!r}, {len(text)} chars)")


@resume_app.command("list")
def resume_list() -> None:
    rows = _resumes_repo().list()
    if not rows:
        typer.echo("\nNo resumes yet. Use `oc resume add --file path/to/resume.txt`.")
        return
    typer.echo("\nResumes")
    typer.echo("--------------------------------------------------------")
    typer.echo(f"{'ID':<4} {'Name':<20} {'Status':<12} {'Chars':<12}")
    for row in rows:
        name = row.name or "(unnamed)"
        typer.echo(f"{row.id:<4} {_truncate(name, 20):<20} {row.parse_status:<12} {len(row.parsed_data):<12}")


@resume_app.command("match")
def resume_match(
    resume_id: int = typer.Option(..., "--resume", "-r", help="resume ID"),
    jd: str = typer.Option("", "--jd", "-j", help="JD text to match (use '-' to read stdin)"),
    jd_url: str = typer.Option("", "--jd-url", "-u", help="JD page URL to fetch then match"),
    app_id: int = typer.Option(0, "--app", "-a", help="linked application ID"),
) -> None:
    jd_text = _read_dash_stdin(jd)
    if bool(jd_text) == bool(jd_url):
        raise typer.BadParameter("provide exactly one of --jd or --jd-url")
    try:
        result = match_resume(
            _build_ai_model(),
            _resumes_repo(),
            resume_id=resume_id,
            jd_text=jd_text,
            jd_url=jd_url,
            application_id=app_id if app_id > 0 else None,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    score = result.result.get("match_score")
    typer.echo(f"\nResume match saved  (id: {result.id}, resume: {result.resume_id})")
    if score is not None:
        typer.echo(f"Score: {score}")
    summary = str(result.result.get("summary") or "")
    if summary:
        typer.echo(f"Summary: {summary}")


@note_app.command("add")
def note_add(
    app_id: int = typer.Option(..., "--app", "-a", help="application ID to link"),
    company: str = typer.Option("", "--company", help="company name"),
    position: str = typer.Option("", "--position", help="position name"),
    round: str = typer.Option("", "--round", "-r", help="interview round"),
    date: str = typer.Option("", "--date", help="interview date"),
    questions: str = typer.Option("", "--questions", "-q", help="interview questions"),
    reflection: str = typer.Option("", "--reflection", "-f", help="self reflection"),
    difficulty: str = typer.Option("", "--difficulty", help="difficult points"),
    mood: str = typer.Option("", "--mood", help="mood"),
) -> None:
    applications = _applications_repo()
    app_model = applications.get(app_id)
    if app_model is None:
        raise typer.BadParameter(f"application #{app_id} not found")
    company = company or app_model.company_name
    position = position or app_model.position_name
    created = _notes_repo().create(
        NoteCreate(
            application_id=app_id,
            company=company,
            position=position,
            round=round,
            date=date,
            questions=questions,
            self_reflection=reflection,
            difficulty_points=difficulty,
            mood=mood,
        )
    )
    typer.echo(f"\nNote saved  (id: {created.id}, {company} - {position} - {round})")


@note_app.command("list")
def note_list(
    app_id: int = typer.Option(0, "--app", "-a", help="filter by application ID"),
) -> None:
    rows = _notes_repo().list(application_id=app_id)
    if not rows:
        typer.echo("\nNo interview notes.")
        return
    typer.echo("\nInterview Notes")
    typer.echo("-------------------------------------------------------------")
    for row in rows:
        typer.echo(f"#{row.id}  {row.company} - {row.position} - {row.round} - {row.date} - mood:{row.mood}")
        if row.questions:
            typer.echo(f"   Questions: {_truncate(row.questions, 60)}")
        if row.self_reflection:
            typer.echo(f"   Reflection: {_truncate(row.self_reflection, 60)}")
        if row.difficulty_points:
            typer.echo(f"   Difficulty: {_truncate(row.difficulty_points, 60)}")


@offer_app.command("add")
def offer_add(
    company: str = typer.Option("", "--company", "-c", help="company name"),
    position: str = typer.Option("", "--position", help="position name"),
    app_id: int = typer.Option(0, "--app", "-a", help="linked application ID"),
    base: int = typer.Option(0, "--base", help="monthly base salary"),
    months: int = typer.Option(12, "--months", help="months per year"),
    signing: int = typer.Option(0, "--signing", help="signing bonus"),
    equity: str = typer.Option("", "--equity", help="equity description"),
    perks: str = typer.Option("", "--perks", help="perks description"),
    deadline: str = typer.Option("", "--deadline", help="offer deadline"),
    notes: str = typer.Option("", "--notes", "-n", help="notes"),
) -> None:
    if base < 0 or signing < 0:
        raise typer.BadParameter("--base and --signing must be non-negative")
    if months < 1:
        raise typer.BadParameter("--months must be at least 1")
    application_id = app_id if app_id > 0 else None
    if application_id is not None:
        app_model = _applications_repo().get(application_id)
        if app_model is not None:
            company = company or app_model.company_name
            position = position or app_model.position_name
    if not company or not position:
        raise typer.BadParameter("--company and --position are required")
    created = _offers_repo().create(
        OfferCreate(
            application_id=application_id,
            company_name=company,
            position_name=position,
            base_monthly=base,
            months_per_year=months,
            signing_bonus=signing,
            equity=equity,
            perks=perks,
            deadline=deadline,
            notes=notes,
        )
    )
    typer.echo(
        f"\nOffer added: {created.company_name} - {created.position_name} "
        f"({created.base_monthly}x{created.months_per_year} + {created.signing_bonus}, total {created.total_cash})"
    )


@offer_app.command("list")
def offer_list(status: str = typer.Option("", "--status", "-s", help="filter by status")) -> None:
    rows = _offers_repo().list(status=status)
    if not rows:
        typer.echo("\nNo offers found. Use 'oc offer add' to add one.")
        return
    typer.echo("\nOffers")
    typer.echo("--------------------------------------------------------------")
    typer.echo(f"{'ID':<4} {'Company':<16} {'Position':<14} {'Status':<12} {'BasexM':<10} {'Total':<10}")
    for row in rows:
        typer.echo(
            f"{row.id:<4} {_truncate(row.company_name, 16):<16} {_truncate(row.position_name, 14):<14} "
            f"{row.status:<12} {str(row.base_monthly) + 'x' + str(row.months_per_year):<10} {row.total_cash:<10}"
        )


@offer_app.command("update")
def offer_update(
    offer_id: int = typer.Argument(...),
    status: Optional[str] = typer.Option(None, "--status", help="new status"),
    base: Optional[int] = typer.Option(None, "--base", help="monthly base salary"),
    months: Optional[int] = typer.Option(None, "--months", help="months per year"),
    signing: Optional[int] = typer.Option(None, "--signing", help="signing bonus"),
) -> None:
    repo = _offers_repo()
    existing = repo.get(offer_id)
    if existing is None:
        raise typer.BadParameter("offer not found")
    next_months = months if months is not None else existing.months_per_year
    if next_months < 1:
        raise typer.BadParameter("months must be at least 1")
    updated = repo.update(
        offer_id,
        OfferCreate(
            application_id=existing.application_id,
            company_name=existing.company_name,
            position_name=existing.position_name,
            status=status if status is not None else existing.status,
            base_monthly=base if base is not None else existing.base_monthly,
            months_per_year=next_months,
            signing_bonus=signing if signing is not None else existing.signing_bonus,
            equity=existing.equity,
            perks=existing.perks,
            deadline=existing.deadline,
            notes=existing.notes,
            assessment=existing.assessment,
        ),
    )
    if updated is None:
        raise typer.BadParameter("offer not found")
    typer.echo(f"\nOffer #{offer_id} updated (status {updated.status}, total {updated.total_cash})")


@offer_app.command("delete")
def offer_delete(offer_id: int = typer.Argument(...)) -> None:
    _offers_repo().delete(offer_id)
    typer.echo(f"\nOffer #{offer_id} deleted")


@offer_app.command("compare")
def offer_compare(ids: str = typer.Argument(...)) -> None:
    repo = _offers_repo()
    rows = []
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        offer = repo.get(int(raw))
        if offer is not None:
            rows.append(offer)
    if not rows:
        typer.echo("\nNo matching offers.")
        return
    typer.echo("\nOffer Compare")
    typer.echo("--------------------------------------------------------------")
    for row in rows:
        typer.echo(f"#{row.id} {row.company_name} - {row.position_name}: total {row.total_cash}")


@question_app.command("list")
def question_list(
    status: str = typer.Option("", "--status", help="filter by status"),
    kb: int = typer.Option(0, "--kb", help="filter by knowledge base ID"),
) -> None:
    rows = _questions_repo().list(status=status, knowledge_base_id=kb)
    if not rows:
        typer.echo("\nNo questions yet. Try: oc question generate --kb <id>")
        return
    typer.echo("\nQuestion Bank")
    typer.echo("-------------------------------------------------------------")
    for row in rows:
        typer.echo(
            f"#{row.id} [{row.category}/{row.difficulty}] {_truncate(row.question, 60)} "
            f"- status:{row.status} practice:{row.practice_count}"
        )


@question_app.command("generate")
def question_generate(
    source: str = typer.Option("knowledge", "--source", "-s", help="knowledge or notes"),
    kb: int = typer.Option(0, "--kb", help="knowledge base ID"),
    app_id: int = typer.Option(0, "--app", "-a", help="application ID for notes source"),
    count: int = typer.Option(8, "--count", "-n", help="number of questions to generate"),
) -> None:
    try:
        result = generate_questions(
            _build_ai_model(),
            _questions_repo(),
            _knowledge_repo(),
            _notes_repo(),
            source=source,
            knowledge_base_id=kb,
            application_id=app_id,
            count=count,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"\nGenerated {result.count} questions  (skipped duplicates: {result.skipped})")
    for question in result.questions:
        typer.echo(f"#{question.id} [{question.category}/{question.difficulty}] {question.question}")


def main() -> None:
    app()


def _applications_repo() -> ApplicationsRepository:
    return ApplicationsRepository(session_factory_for_data_dir(resolve_data_dir()))


def _jd_repo() -> JDAnalysesRepository:
    return JDAnalysesRepository(session_factory_for_data_dir(resolve_data_dir()))


def _knowledge_repo() -> KnowledgeRepository:
    return KnowledgeRepository(session_factory_for_data_dir(resolve_data_dir()))


def _resumes_repo() -> ResumesRepository:
    return ResumesRepository(session_factory_for_data_dir(resolve_data_dir()))


def _notes_repo() -> NotesRepository:
    return NotesRepository(session_factory_for_data_dir(resolve_data_dir()))


def _offers_repo() -> OffersRepository:
    return OffersRepository(session_factory_for_data_dir(resolve_data_dir()))


def _questions_repo() -> QuestionsRepository:
    return QuestionsRepository(session_factory_for_data_dir(resolve_data_dir()))


def _build_ai_model() -> ConfiguredAIClient:
    return ConfiguredAIClient(load_config(resolve_data_dir()))


def _read_dash_stdin(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    return value


def _print_config(data_dir: Path, cfg: Config) -> None:
    active = cfg.active_provider()
    typer.echo("\nOfferPilot Configuration")
    typer.echo("---------------------------")
    typer.echo(f"Config file: {data_dir / 'config.json'}")
    typer.echo(f"  provider : {active.provider}")
    typer.echo(f"  base_url : {active.base_url}")
    typer.echo(f"  model    : {active.model}")
    if active.api_key:
        typer.echo(f"  api_key  : {_mask_key(active.api_key)}")
    else:
        typer.echo("  api_key  : (not set - AI features will return an error)")
    typer.echo(f"  local_port: {cfg.local_port}")
    typer.echo(f"  runtime_mode: {cfg.runtime_mode}")
    typer.echo(f"  auth_enabled: {_format_bool(cfg.auth_enabled)}")
    typer.echo(f"  log_level: {cfg.log_level}")
    typer.echo(f"  ai_auto_approve: {_format_bool(cfg.chat_auto_approve_writes)}")


def _sync_active_provider_config(
    cfg: Config,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> Config:
    active = cfg.active_provider()
    providers = []
    for profile in cfg.provider_profiles():
        if profile.id == active.id:
            providers.append(
                profile.model_copy(
                    update={
                        "api_key": api_key if api_key is not None else profile.api_key,
                        "base_url": base_url if base_url is not None else profile.base_url,
                        "model": model if model is not None else profile.model,
                    }
                )
            )
        else:
            providers.append(profile)
    if not providers:
        providers = [
            AIProviderProfile(
                id=active.id,
                label=active.label,
                provider=active.provider,
                api_key=api_key if api_key is not None else active.api_key,
                base_url=base_url if base_url is not None else active.base_url,
                model=model if model is not None else active.model,
                enabled=active.enabled,
            )
        ]
    return cfg.model_copy(update={"providers": providers})


def _set_skill_state(
    skill_id: str,
    *,
    trusted: bool | None = None,
    enabled: bool | None = None,
) -> None:
    data_dir = resolve_data_dir()
    payload = {}
    if trusted is not None:
        payload["trusted"] = trusted
    if enabled is not None:
        payload["enabled"] = enabled
    try:
        next_config = update_skill(load_config(data_dir), skill_id, payload)
    except KeyError as exc:
        raise typer.BadParameter("skill not found") from exc
    except SkillRegistryError as exc:
        raise typer.BadParameter(str(exc)) from exc
    save_config(data_dir, next_config)


def _mask_key(value: str) -> str:
    if len(value) <= 6:
        return "******"
    return value[:4] + "****" + value[-2:]


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _truncate(value: str, limit: int) -> str:
    if len(value) > limit:
        return value[: limit - 1] + "..."
    return value

from __future__ import annotations

from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_specs.application_events import application_event_specs
from offerpilot.ai.tool_specs.applications import application_specs
from offerpilot.ai.tool_specs.jd_analyses import jd_analysis_specs
from offerpilot.ai.tool_specs.notes import note_specs
from offerpilot.ai.tool_specs.offers import offer_specs
from offerpilot.ai.tool_specs.resumes import resume_specs


MODEL_TOOL_NAMES = (
    "list_applications",
    "get_application",
    "create_application",
    "update_application_status",
    "list_application_events",
    "get_application_event",
    "create_application_event",
    "update_application_event",
    "delete_application_event",
    "list_notes",
    "add_note",
    "update_note",
    "delete_note",
    "list_offers",
    "get_offer",
    "compare_offers",
    "update_offer",
    "save_offer_assessment",
    "list_resumes",
    "get_resume",
    "resume_update_career_intent",
    "resume_rewrite_highlight",
    "list_resume_matches",
    "list_jd_analyses",
    "get_jd_analysis",
)


def build_model_tool_catalog() -> ToolCatalog:
    specs = (
        *application_specs(),
        *application_event_specs(),
        *note_specs(),
        *offer_specs(),
        *resume_specs(),
        *jd_analysis_specs(),
    )
    return ToolCatalog(specs, expected_names=MODEL_TOOL_NAMES)


MODEL_TOOL_CATALOG = build_model_tool_catalog()

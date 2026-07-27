from __future__ import annotations

import json

from sqlalchemy import inspect, select, text

from offerpilot.db import init_database
from offerpilot.models import OpportunityFitReview


def test_fresh_database_creates_v2_review_root_and_stage_tables(tmp_path) -> None:
    factory = init_database(tmp_path / "data.db")

    with factory() as session:
        table_names = set(inspect(session.bind).get_table_names())
        assert "opportunity_fit_review_sessions" in table_names
        assert "opportunity_fit_review_stages" in table_names
        migration = session.execute(
            text("SELECT version FROM schema_migrations WHERE version = '0013_opportunity_fit_v2'")
        ).scalar_one()
        assert migration == "0013_opportunity_fit_v2"
        assert session.execute(
            text("SELECT version FROM schema_migrations WHERE version = '0014_opportunity_fit_v1_schema_marker'")
        ).scalar_one() == "0014_opportunity_fit_v1_schema_marker"


def test_existing_v1_review_bytes_and_hashes_survive_v2_migration(tmp_path) -> None:
    db_path = tmp_path / "data.db"
    factory = init_database(db_path)
    snapshot = json.dumps({"jd": "JD"}, separators=(",", ":"))
    triage = json.dumps({"recommendation": "hold"}, separators=(",", ":"))
    with factory() as session:
        session.execute(
            text(
                """
                INSERT INTO applications (company_name, position_name, source, status)
                VALUES ('Acme', 'Backend', 'manual', 'applied')
                """
            )
        )
        application_id = session.execute(text("SELECT last_insert_rowid()")).scalar_one()
        session.execute(
            text(
                """
                INSERT INTO opportunity_fit_reviews (
                    application_id, resume_id, idempotency_key,
                    source_fingerprint_sha256, source_snapshot_json,
                    triage_json, triage_sha256
                ) VALUES (:application_id, NULL, 'legacy-key', 'source-hash', :snapshot,
                          :triage, 'triage-hash')
                """
            ),
            {"application_id": application_id, "snapshot": snapshot, "triage": triage},
        )
        session.commit()

    init_database(db_path)

    with factory() as session:
        row = session.scalar(select(OpportunityFitReview))
        assert row is not None
        assert row.source_snapshot_json == snapshot
        assert row.triage_json == triage
        assert row.source_fingerprint_sha256 == "source-hash"
        assert row.triage_sha256 == "triage-hash"
        assert row.proposal_schema_version == 1
        assert session.execute(
            text("SELECT COUNT(*) FROM opportunity_fit_review_stages")
        ).scalar_one() == 0

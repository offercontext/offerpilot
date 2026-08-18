from sqlalchemy import inspect, text

from offerpilot.db import init_database


def test_confirmation_claim_column_and_migration_are_durable(tmp_path) -> None:
    session_factory = init_database(tmp_path / "data.db")
    engine = session_factory.kw["bind"]

    columns = {column["name"] for column in inspect(engine).get_columns("conversations")}
    with engine.connect() as connection:
        migration_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM schema_migrations "
                "WHERE version = '0025_pending_confirmation_claim'"
            )
        ).scalar_one()

    assert "pending_confirmation_claim_id" in columns
    assert migration_count == 1

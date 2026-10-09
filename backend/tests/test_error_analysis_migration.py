"""Regression checks for the additive governed Error Analysis migration."""

from pathlib import Path

from pglast import parse_sql

MIGRATION = (
    Path(__file__).resolve().parents[2] / "supabase/migrations/202610020002_error_analysis.sql"
)


def test_error_analysis_migration_parses_and_keeps_all_categories_and_pilot_gates():
    source = MIGRATION.read_text()
    parse_sql(source)
    for category in (
        "master_data",
        "mapping",
        "integration_mapping",
        "master_data_restriction",
        "posting_period",
        "tax",
        "currency",
        "document_splitting",
        "account_assignment",
        "technical_interface",
    ):
        assert f"'{category}'" in source
    assert "record_process_owner_decision" in source
    assert "Recorded Process Owner approval is required before master-data implementation" in source
    assert "Recorded Process Owner approval is required before reprocessing" in source
    assert "Each route evidence ID must be saved proof for this case" in source
    assert "error_analysis_complete_run" in source

from pathlib import Path

from pglast import parse_sql


def test_foundation_is_valid_postgresql_syntax():
    path = Path(__file__).resolve().parents[2] / "supabase/migrations/202609300001_foundation.sql"
    assert parse_sql(path.read_text())

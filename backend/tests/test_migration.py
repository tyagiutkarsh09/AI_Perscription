from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy import Column
from sqlalchemy.dialects import mysql

from app.models import Base


def test_initial_migration_enforces_append_only_logs(monkeypatch):
    path = Path(__file__).parents[1] / "migrations/versions/0001_initial_schema.py"
    spec = spec_from_file_location("initial_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    created = {}

    def capture_table(name, *items):
        created[name] = [item for item in items if isinstance(item, Column)]

    monkeypatch.setattr(migration.op, "create_table", capture_table)
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    assert set(created) == set(Base.metadata.tables)
    for name, columns in created.items():
        model_columns = Base.metadata.tables[name].c
        assert [column.name for column in columns] == list(model_columns.keys())
        assert [column.nullable for column in columns] == [
            column.nullable for column in model_columns
        ]
        assert [column.type.compile(dialect=mysql.dialect()) for column in columns] == [
            column.type.compile(dialect=mysql.dialect()) for column in model_columns
        ]

    for table in ("safety_events", "audit_log"):
        assert any(f"{table}_no_update" in sql for sql in statements)
        assert any(f"{table}_no_delete" in sql for sql in statements)
    assert sum("SIGNAL SQLSTATE '45000'" in sql for sql in statements) == 4

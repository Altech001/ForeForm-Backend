from sqlalchemy import inspect, text


def _column_exists(inspector, table_name, column_name):
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def ensure_quiz_columns(engine):
    """Add quiz/presentation columns for deployments that already have tables."""
    inspector = inspect(engine)
    dialect = engine.dialect.name

    json_type = "JSONB" if dialect == "postgresql" else "JSON"
    bool_type = "BOOLEAN"

    columns = [
        ("forms", "quiz", json_type),
        ("forms", "presentation", json_type),
        ("form_responses", "quiz_score", "FLOAT"),
        ("form_responses", "quiz_max_score", "FLOAT"),
        ("form_responses", "quiz_percent", "FLOAT"),
        ("form_responses", "grades_released", bool_type),
    ]

    with engine.begin() as conn:
        for table_name, column_name, column_type in columns:
            if not _column_exists(inspector, table_name, column_name):
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))

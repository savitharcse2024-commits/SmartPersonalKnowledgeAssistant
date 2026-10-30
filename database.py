import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

DATABASE_PATH = Path(__file__).parent / "knowledge.db"
REQUIRED_NOTES_COLUMNS = {
    "id",
    "title",
    "content",
    "tags",
    "category",
    "created_at",
    "updated_at",
}
def create_database(database_path=DATABASE_PATH):
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT,
                    category TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    note_date TEXT NOT NULL DEFAULT CURRENT_DATE,
                    source TEXT NOT NULL DEFAULT ''
                )
            """)

            existing_columns = {
                column[1]
                for column in connection.execute("PRAGMA table_info(notes)")
            }
            if not {"id", "title", "content"}.issubset(existing_columns):
                raise sqlite3.DatabaseError(
                    "The notes table is missing a required id, title, or content column."
                )

            metadata_columns_added = False
            for column, definition in (
                ("tags", "TEXT"),
                ("category", "TEXT"),
                ("created_at", "TEXT NOT NULL DEFAULT ''"),
                ("updated_at", "TEXT NOT NULL DEFAULT ''"),
                ("note_date", "TEXT NOT NULL DEFAULT ''"),
                ("source", "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE notes ADD COLUMN {column} {definition}"
                    )
                    metadata_columns_added = True

            if metadata_columns_added:
                connection.execute(
                    """
                    UPDATE notes
                    SET created_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP),
                        updated_at = COALESCE(NULLIF(updated_at, ''), CURRENT_TIMESTAMP),
                        note_date = COALESCE(NULLIF(note_date, ''), date(created_at), CURRENT_DATE)
                    WHERE created_at IS NULL OR created_at = ''
                       OR updated_at IS NULL OR updated_at = ''
                       OR note_date IS NULL OR note_date = ''
                    """
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_title_normalized "
                "ON notes(lower(trim(title)))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_note_date ON notes(note_date)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_source ON notes(source)"
            )
            fts_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'notes_fts'"
            ).fetchone()
            connection.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    title, content, category, tags, source,
                    content='notes', content_rowid='id'
                )
            """)
            connection.executescript("""
                CREATE TRIGGER IF NOT EXISTS notes_fts_insert
                AFTER INSERT ON notes BEGIN
                    INSERT INTO notes_fts(rowid, title, content, category, tags, source)
                    VALUES (new.id, new.title, new.content, new.category, new.tags, new.source);
                END;
                CREATE TRIGGER IF NOT EXISTS notes_fts_delete
                AFTER DELETE ON notes BEGIN
                    INSERT INTO notes_fts(notes_fts, rowid, title, content, category, tags, source)
                    VALUES ('delete', old.id, old.title, old.content, old.category, old.tags, old.source);
                END;
                CREATE TRIGGER IF NOT EXISTS notes_fts_update
                AFTER UPDATE ON notes BEGIN
                    INSERT INTO notes_fts(notes_fts, rowid, title, content, category, tags, source)
                    VALUES ('delete', old.id, old.title, old.content, old.category, old.tags, old.source);
                    INSERT INTO notes_fts(rowid, title, content, category, tags, source)
                    VALUES (new.id, new.title, new.content, new.category, new.tags, new.source);
                END;
            """)
            if not fts_exists:
                connection.execute(
                    "INSERT INTO notes_fts(notes_fts) VALUES ('rebuild')"
                )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS saved_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_id INTEGER,
                    note_title TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    note_date TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
                )
            """)


def check_database(database_path=DATABASE_PATH):
    with closing(sqlite3.connect(database_path)) as connection:
        result = connection.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'notes'
        """).fetchone()

    if result:
        print("Success: the 'notes' table exists.")
    else:
        print("Problem: the 'notes' table was not found.")


def _validate_backup(backup_path):
    with closing(sqlite3.connect(backup_path)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise sqlite3.DatabaseError("The backup failed SQLite integrity check.")

        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'notes'"
        ).fetchone()
        if table_exists is None:
            raise sqlite3.DatabaseError("The backup does not contain a notes table.")

        columns = {
            column[1] for column in connection.execute("PRAGMA table_info(notes)")
        }
        if not REQUIRED_NOTES_COLUMNS.issubset(columns):
            raise sqlite3.DatabaseError(
                "The backup notes table does not have the expected schema."
            )


def is_valid_backup(backup_bytes):
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_path = Path(temporary_directory) / "uploaded_backup.db"
            backup_path.write_bytes(backup_bytes)
            _validate_backup(backup_path)
    except (OSError, sqlite3.Error):
        return False
    return True


def create_backup(database_path=DATABASE_PATH):
    with tempfile.TemporaryDirectory() as temporary_directory:
        backup_path = Path(temporary_directory) / "knowledge_backup.db"
        with closing(sqlite3.connect(database_path)) as source:
            with source:
                with closing(sqlite3.connect(backup_path)) as destination:
                    with destination:
                        source.backup(destination)
        return backup_path.read_bytes()


def restore_backup(backup_bytes, database_path=DATABASE_PATH):
    with tempfile.TemporaryDirectory() as temporary_directory:
        backup_path = Path(temporary_directory) / "uploaded_backup.db"
        backup_path.write_bytes(backup_bytes)
        _validate_backup(backup_path)

        with closing(sqlite3.connect(backup_path)) as source:
            with source:
                with closing(sqlite3.connect(database_path)) as destination:
                    with destination:
                        source.backup(destination)
    create_database(database_path)


if __name__ == "__main__":
    create_database()
    print(f"Database is ready: {DATABASE_PATH}")
    check_database()
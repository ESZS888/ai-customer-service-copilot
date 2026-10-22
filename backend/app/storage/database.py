"""Single local SQLite file. Connections never span an LLM request."""
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import sqlite3
from app.config import settings


class Database:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            if con.execute('PRAGMA user_version').fetchone()[0] > 2:
                raise sqlite3.DatabaseError('Unsupported database schema version')
            con.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
            if 'business_intent' not in {r['name'] for r in con.execute('PRAGMA table_info(chat_turns)')}:
                con.execute('ALTER TABLE chat_turns ADD COLUMN business_intent TEXT')
            from app.storage.repository import business_intent
            for row in con.execute("SELECT request_id,message,intent FROM chat_turns WHERE status='succeeded' AND business_intent IS NULL").fetchall():
                con.execute('UPDATE chat_turns SET business_intent=? WHERE request_id=?',
                            (business_intent(row['message'], row['intent']), row['request_id']))
            con.execute('PRAGMA user_version = 2')

    @contextmanager
    def connect(self, write=False):
        con = sqlite3.connect(self.path, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys = ON')
        con.execute('PRAGMA busy_timeout = 5000')
        try:
            if write:
                con.execute('BEGIN IMMEDIATE')
            else:
                con.execute('BEGIN')
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()


@lru_cache(maxsize=4)
def _repository(path):
    from app.storage.repository import Repository
    return Repository(Database(path))


def get_repository():
    return _repository(str(Path(settings.db_path).resolve()))

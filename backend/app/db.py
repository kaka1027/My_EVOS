from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg2
import psycopg2.extras

from .config import settings


@contextmanager
def get_cursor() -> Iterator[psycopg2.extras.RealDictCursor]:
    conn = psycopg2.connect(**settings.pg_dsn())
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

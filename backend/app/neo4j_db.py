from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from neo4j import Driver, GraphDatabase, Session

from .config import settings


@contextmanager
def get_session() -> Iterator[Session]:
    if not settings.neo4j_password:
        raise RuntimeError("NEO4J_PASSWORD is not configured")
    driver: Driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        with driver.session() as session:
            yield session
    finally:
        driver.close()


def verify_connection() -> bool:
    try:
        with get_session() as session:
            session.run("RETURN 1 AS ok").single()
        return True
    except Exception:
        return False

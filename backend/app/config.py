from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    pg_host: str = os.environ.get("PGHOST", "127.0.0.1")
    pg_port: int = int(os.environ.get("PGPORT", "54329"))
    pg_user: str = os.environ.get("PGUSER", "postgres")
    pg_password: str = os.environ.get("PGPASSWORD", "")
    pg_database: str = os.environ.get("PGDATABASE", "evos")
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    )

    def pg_dsn(self) -> dict:
        dsn = {
            "host": self.pg_host,
            "port": self.pg_port,
            "user": self.pg_user,
            "dbname": self.pg_database,
        }
        if self.pg_password:
            dsn["password"] = self.pg_password
        return dsn


settings = Settings()

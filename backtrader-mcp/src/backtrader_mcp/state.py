"""Durable SQLite registry used by every product service."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable

from .errors import Conflict, NotFound
from .util import canonical_json, sha256_json, utc_now


class StateStore:
    def __init__(self, state_root: Path):
        self.path = state_root / "state.sqlite3"
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS objects (
                    kind TEXT NOT NULL,
                    id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (kind, id)
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (scope, key)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    event TEXT NOT NULL,
                    subject_id TEXT,
                    details_json TEXT NOT NULL
                );
                """)

    def put(
        self, kind: str, object_id: str, payload: dict[str, Any], *, replace: bool = False
    ) -> None:
        now = utc_now()
        sql = (
            "INSERT OR REPLACE INTO objects(kind,id,payload_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?)"
            if replace
            else "INSERT INTO objects(kind,id,payload_json,created_at,updated_at) VALUES(?,?,?,?,?)"
        )
        try:
            with self.connect() as connection:
                connection.execute(sql, (kind, object_id, canonical_json(payload), now, now))
        except sqlite3.IntegrityError as exc:
            raise Conflict(f"{kind} already exists: {object_id}") from exc

    def get(self, kind: str, object_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM objects WHERE kind=? AND id=?", (kind, object_id)
            ).fetchone()
        if row is None:
            raise NotFound(f"{kind} not found: {object_id}")
        return json.loads(row["payload_json"])

    def maybe_get(self, kind: str, object_id: str) -> dict[str, Any] | None:
        try:
            return self.get(kind, object_id)
        except NotFound:
            return None

    def list(self, kind: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM objects WHERE kind=? ORDER BY created_at,id", (kind,)
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def update(
        self, kind: str, object_id: str, mutator: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM objects WHERE kind=? AND id=?", (kind, object_id)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise NotFound(f"{kind} not found: {object_id}")
            new_payload = mutator(json.loads(row["payload_json"]))
            connection.execute(
                "UPDATE objects SET payload_json=?,updated_at=? WHERE kind=? AND id=?",
                (canonical_json(new_payload), utc_now(), kind, object_id),
            )
            connection.commit()
        return new_payload

    def idempotent_get(
        self, scope: str, key: str, request: dict[str, Any]
    ) -> dict[str, Any] | None:
        request_hash = sha256_json(request)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT request_hash,response_json FROM idempotency WHERE scope=? AND key=?",
                (scope, key),
            ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise Conflict("idempotency key was already used with a different request")
        return json.loads(row["response_json"])

    def idempotent_put(
        self, scope: str, key: str, request: dict[str, Any], response: dict[str, Any]
    ) -> None:
        try:
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO idempotency(scope,key,request_hash,response_json,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (scope, key, sha256_json(request), canonical_json(response), utc_now()),
                )
        except sqlite3.IntegrityError:
            prior = self.idempotent_get(scope, key, request)
            if prior != response:
                raise Conflict("concurrent idempotency response differs")

    def create_approval(
        self, subject_type: str, subject_id: str, subject_hash: str, expires_at: str
    ) -> dict[str, Any]:
        approval_id = f"approval_{uuid.uuid4().hex}"
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO approvals VALUES(?,?,?,?,?,?,NULL)",
                (approval_id, subject_type, subject_id, subject_hash, created_at, expires_at),
            )
        result = {
            "approval_id": approval_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "subject_hash": subject_hash,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        self.audit("approval.created", subject_id, result)
        return result

    def consume_approval(
        self, approval_id: str, subject_type: str, subject_id: str, subject_hash: str
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            if (
                row is None
                or row["subject_type"] != subject_type
                or row["subject_id"] != subject_id
                or row["subject_hash"] != subject_hash
                or row["used_at"] is not None
                or row["expires_at"] <= now
            ):
                connection.rollback()
                raise Conflict("approval is missing, expired, used, or bound to different content")
            connection.execute(
                "UPDATE approvals SET used_at=? WHERE approval_id=?", (now, approval_id)
            )
            connection.commit()
        self.audit("approval.consumed", subject_id, {"approval_id": approval_id})

    def audit(self, event: str, subject_id: str | None, details: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO audit(at,event,subject_id,details_json) VALUES(?,?,?,?)",
                (utc_now(), event, subject_id, canonical_json(details)),
            )

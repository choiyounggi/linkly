"""FastAPI equivalent of examples/linkhub.lnpl (issue #142 token benchmark).

Behavioral parity target: examples/linkhub.lnpl (LNPL 0.6.0, the LinkHub
golden scenario). See ../equiv/MAPPING.md for the entity/endpoint/validation/
cache-TTL/retry mapping table that defines what "equivalent" means here.

Not a production service: the repository, cache, and event log are
in-memory dicts (mirroring LNPL's own default `fake` capability driver used
by `lnpl spec --run`), so behavior is directly comparable across the two
implementations without standing up postgres/redis.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, TypeVar

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

# entity Bookmark — field id/url/title/owner/savedAt/visits
URL_PATTERN = re.compile(r"^https?://[^\s]+$")
URL_MAX_LENGTH = 2048

# service LinkHubService — performance cache 5m
CACHE_TTL_SECONDS = 5 * 60

# service LinkHubService — policy retry 3
RETRY_ATTEMPTS = 3

T = TypeVar("T")


class RepositoryConflictError(Exception):
    """Mirrors LNPL's `repository create conflicts: entity.bookmark already exists`."""


class RepositoryNotFoundError(Exception):
    """Mirrors LNPL's `repository read found no row for entity.bookmark`."""


class BookmarkCreate(BaseModel):
    id: str
    url: str
    title: str
    owner: str
    note: str = ""

    @field_validator("url")
    @classmethod
    def url_matches_pattern(cls, value: str) -> str:
        # refine URL of Text: maxLength=2048, pattern=^https?://[^\s]+$
        if len(value) > URL_MAX_LENGTH or not URL_PATTERN.match(value):
            raise ValueError("does not match URL's pattern")
        return value


@dataclass
class Bookmark:
    id: str
    url: str
    title: str
    owner: str
    savedAt: str
    visits: int = 0  # refine VisitCount of Integer: min 0
    note: str = ""


@dataclass
class Store:
    """Fake repository + cache + event log — one instance per app/run."""

    bookmarks: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)
    events: list = field(default_factory=list)


def with_retry(attempts: int, fn: Callable[[], T]) -> T:
    """policy retry 3 — re-run a failed (idempotent) repository read."""
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            return fn()
        except RepositoryNotFoundError as exc:
            last_exc = exc
    assert last_exc is not None
    raise last_exc


def create_bookmark(store: Store, payload: BookmarkCreate) -> Bookmark:
    # create bookmark — repository create; conflicts if the id already exists
    if payload.id in store.bookmarks:
        raise RepositoryConflictError(
            "repository create conflicts: entity.bookmark already exists"
        )
    row = Bookmark(
        id=payload.id,
        url=payload.url,
        title=payload.title,
        owner=payload.owner,
        savedAt=datetime.now(timezone.utc).isoformat(),
        visits=0,
        note=payload.note,
    )
    store.bookmarks[row.id] = row
    return row


def cache_bookmark(store: Store, row: Bookmark) -> None:
    # cache bookmark — CacheAccess set, TTL from performance.cache (5m)
    store.cache[f"bookmark:{row.id}"] = {
        "value": row,
        "expires_at": time.monotonic() + CACHE_TTL_SECONDS,
    }


def emit_bookmark_saved(store: Store, row: Bookmark) -> None:
    # emit bookmarkSaved — event Bookmark create
    store.events.append({"name": "BookmarkSaved", "bookmark_id": row.id})


def find_bookmark(store: Store, bookmark_id: str) -> Bookmark:
    # find bookmark — repository read; fails hard when absent
    row = store.bookmarks.get(bookmark_id)
    if row is None:
        raise RepositoryNotFoundError(
            "repository read found no row for entity.bookmark"
        )
    return row


def save_bookmark(store: Store, payload: BookmarkCreate) -> Bookmark:
    """workflow SaveBookmark: validate input -> pipeline persist(create, cache, emit)."""
    row = create_bookmark(store, payload)
    cache_bookmark(store, row)
    emit_bookmark_saved(store, row)
    return row


def get_bookmark(store: Store, bookmark_id: str) -> Bookmark:
    """workflow GetBookmark: validate input -> find bookmark (policy retry 3)."""
    return with_retry(RETRY_ATTEMPTS, lambda: find_bookmark(store, bookmark_id))


def create_app() -> FastAPI:
    app = FastAPI(title="linkhub-fastapi")
    app.state.store = Store()

    @app.post("/bookmarks", status_code=201)
    def post_bookmark(payload: BookmarkCreate):
        try:
            row = save_bookmark(app.state.store, payload)
        except RepositoryConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": row.id,
            "url": row.url,
            "title": row.title,
            "owner": row.owner,
            "savedAt": row.savedAt,
            "visits": row.visits,
            "note": row.note,
        }

    @app.get("/bookmarks/{bookmark_id}")
    def get_bookmark_route(bookmark_id: str):
        try:
            row = get_bookmark(app.state.store, bookmark_id)
        except RepositoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "id": row.id,
            "url": row.url,
            "title": row.title,
            "owner": row.owner,
            "savedAt": row.savedAt,
            "visits": row.visits,
            "note": row.note,
        }

    return app


app = create_app()


def new_bookmark_id() -> str:
    return str(uuid.uuid4())

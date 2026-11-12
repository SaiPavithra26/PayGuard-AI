"""Declarative base and custom SQLAlchemy types for PayLater Shield."""

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.orm import DeclarativeBase


class UTCDateTime(TypeDecorator):
    """Custom SQLAlchemy type ensuring datetimes are timezone-aware in UTC.

    SQLite stores datetimes as strings without timezone offsets by default.
    This type decorator ensures:
    1. Outgoing datetimes are normalized to UTC.
    2. Incoming datetimes retrieved from the database are always timezone-aware with UTC tzinfo.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime object, received {type(value).__name__}")
        if value.tzinfo is None:
            # If naive datetime is provided, treat as UTC
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


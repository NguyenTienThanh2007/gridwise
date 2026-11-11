import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gridwise_api.models.base import Base


class Organization(Base):
    """The tenant. Every tenant-owned table references it (docs/decisions/0004)."""

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    # Maintained by the core.set_updated_at() trigger, never by application code.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), server_onupdate=FetchedValue()
    )

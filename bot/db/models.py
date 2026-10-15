from datetime import datetime
from sqlalchemy import BigInteger, String, JSON, DateTime, Text, Integer
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    institute_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Schedule(Base):
    __tablename__ = "schedules"

    group_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    institute_id: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Institute(Base):
    __tablename__ = "institutes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    groups_count: Mapped[int] = mapped_column(Integer, default=0)


class ErrorReport(Base):
    __tablename__ = "error_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    group_code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

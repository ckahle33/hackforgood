import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

CAUSES = [
    "Animals", "Arts & Culture", "Children & Youth", "Climate & Environment",
    "Disaster Relief", "Education", "Health", "Hunger & Housing",
    "Human Rights", "Seniors", "Veterans", "Other",
]
JOB_TYPES = ["Full-time", "Part-time", "Contract", "Volunteer", "Internship"]


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # Supabase user id
    email: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String, default="")
    avatar_url: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    mission: Mapped[str] = mapped_column(Text)
    website: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    jobs: Mapped[list["Job"]] = relationship(back_populates="org", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    cause: Mapped[str] = mapped_column(String, index=True)
    job_type: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String, default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    apply_url: Mapped[str] = mapped_column(String)
    accept_applications: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # pending -> approved (visible) | rejected | closed
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    org: Mapped[Organization] = relationship(back_populates="jobs")
    applications: Mapped[list["Application"]] = relationship(back_populates="job", cascade="all, delete-orphan")


APPLICATION_STATUSES = ["new", "contacted", "declined"]


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "user_id", name="uq_application_job_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    resume_url: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="new")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    job: Mapped[Job] = relationship(back_populates="applications")

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

CAUSES = [
    "Animals", "Arts & Culture", "Children & Youth", "Climate & Environment",
    "Disaster Relief", "Education", "Health", "Hunger & Housing",
    "Human Rights", "Seniors", "Veterans", "Other",
]
SALARY_PERIODS = {"HOUR": "per hour", "MONTH": "per month", "YEAR": "per year"}
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
    city: Mapped[str] = mapped_column(String, default="")
    region: Mapped[str] = mapped_column(String, default="")  # state / province
    country: Mapped[str] = mapped_column(String, default="US")  # ISO 3166-1 alpha-2; for remote roles, where applicants may live
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String, nullable=True)  # HOUR | MONTH | YEAR (USD)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    apply_url: Mapped[str] = mapped_column(String)
    accept_applications: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # pending -> approved (visible) | rejected | closed
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    org: Mapped[Organization] = relationship(back_populates="jobs")

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=dt.timezone.utc)
        return exp <= now()

    @property
    def salary_display(self) -> str:
        if not self.salary_min and not self.salary_max:
            return ""
        lo, hi = self.salary_min, self.salary_max
        amount = f"${lo:,}" if lo == hi or not hi else f"${lo:,}-${hi:,}" if lo else f"up to ${hi:,}"
        return f"{amount} {SALARY_PERIODS.get(self.salary_period, '')}".strip()

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

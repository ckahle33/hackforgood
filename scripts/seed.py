"""Load a few sample organizations and approved jobs for local development.
Usage: python -m scripts.seed
"""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job, Organization, User

ORGS = [
    ("Riverside Food Bank", "We make sure no neighbor goes hungry.", "Hunger & Housing", [
        ("Volunteer Coordinator", "Recruit and schedule weekend volunteers.", "Volunteer", "Austin, TX", False),
        ("Logistics Manager", "Run warehouse operations and driver routes.", "Full-time", "Austin, TX", False)]),
    ("Open Doors Literacy", "Free tutoring and adult literacy programs.", "Education", [
        ("Online Tutor", "Tutor adult learners over video, evenings.", "Volunteer", "", True),
        ("Program Associate", "Support curriculum and partner schools.", "Full-time", "Chicago, IL", True)]),
    ("Clean Coast Alliance", "Protecting shorelines and marine life.", "Climate & Environment", [
        ("Data Analyst", "Turn beach-cleanup data into policy wins.", "Part-time", "", True)]),
]

with SessionLocal() as db:
    if not db.get(User, "seed-owner"):
        db.add(User(id="seed-owner", email="seed@example.invalid", name="Seed"))
        db.flush()
    for name, mission, cause, jobs in ORGS:
        if db.scalar(select(Organization).where(Organization.name == name)):
            continue
        org = Organization(owner_id="seed-owner", name=name, mission=mission)
        db.add(org)
        db.flush()
        for title, desc, jtype, loc, remote in jobs:
            db.add(Job(org_id=org.id, title=title, description=desc, cause=cause, job_type=jtype,
                       location=loc, remote=remote, apply_url="https://example.org/apply", status="approved"))
    db.commit()
print("seeded")

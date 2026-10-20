"""Idempotent development seed: users, teams and a few sample agents.

Usage: `uv run python -m app.seed`
"""

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Agent
from app.repositories import agent as agent_repo
from app.repositories import agent_team as agent_team_repo
from app.repositories import label as label_repo
from app.repositories import team as team_repo
from app.repositories import user as user_repo
from app.security import hash_password

USERS = [
    ("admin@example.com", "Admin", "admin"),
    ("alice@example.com", "Alice", "member"),
    ("bob@example.com", "Bob", "member"),
]
PASSWORD = "password123"


async def main() -> None:
    async with SessionLocal() as db:
        users = {}
        for email, name, role in USERS:
            user = await user_repo.get_by_email(db, email)
            if user is None:
                user = await user_repo.create(
                    db, email=email, name=name, password_hash=hash_password(PASSWORD), role=role
                )
            users[email] = user

        teams = {}
        for name, description in [
            ("Engineering", "Product engineering"),
            ("Support", "Customer support"),
        ]:
            teams[name] = await team_repo.get_by_name(db, name) or await team_repo.create(
                db, name=name, description=description
            )

        alice, bob = users["alice@example.com"], users["bob@example.com"]
        await team_repo.upsert_member(
            db, team_id=teams["Engineering"].id, user_id=alice.id, role="team_admin"
        )
        await team_repo.upsert_member(
            db, team_id=teams["Engineering"].id, user_id=bob.id, role="member"
        )
        await team_repo.upsert_member(
            db, team_id=teams["Support"].id, user_id=bob.id, role="team_admin"
        )

        if not await db.scalar(select(Agent.id).limit(1)):
            samples = [
                ("Company Assistant", "🤖", "org", users["admin@example.com"], [], {"env": "prod"}),
                ("Code Reviewer", "🧑‍💻", "team", alice, [teams["Engineering"].id], {"env": "dev"}),
                ("Ticket Triage", "🎫", "team", bob, [teams["Support"].id], {"env": "prod"}),
                ("Alice's Scratchpad", "📝", "personal", alice, [], {}),
            ]
            for name, icon, scope, author, team_ids, labels in samples:
                agent = await agent_repo.create(
                    db,
                    name=name,
                    icon=icon,
                    scope=scope,
                    author_id=author.id,
                    description=f"Sample {scope} agent",
                    system_prompt="You are a helpful assistant.",
                )
                await agent_team_repo.sync(db, agent.id, team_ids)
                await label_repo.sync_agent_labels(db, agent.id, list(labels.items()))

        await db.commit()
    print(f"Seeded. Log in as admin@example.com / alice@example.com / bob@example.com ({PASSWORD})")


if __name__ == "__main__":
    asyncio.run(main())

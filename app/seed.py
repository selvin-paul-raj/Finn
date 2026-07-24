"""Database seeding script for Finn.
Creates a default user, default categories, and default accounts if they don't exist.
"""

import asyncio
import sys
from sqlalchemy import select
from app.db import async_session_factory
from app.models import User, Category, Account

async def seed():
    if not async_session_factory:
        print("DATABASE_URL not set in environment.")
        sys.exit(1)

    print("Seeding database...")
    async with async_session_factory() as session:
        # 1. Seed User
        user_res = await session.execute(select(User))
        user = user_res.scalars().first()
        if not user:
            user = User(name="Default User", timezone="Asia/Kolkata")
            session.add(user)
            await session.flush()
            print(f"Created default user: {user.name} ({user.id})")
        else:
            print(f"User already exists: {user.name} ({user.id})")

        # 2. Seed Accounts
        acc_res = await session.execute(select(Account).where(Account.user_id == user.id))
        accounts = acc_res.scalars().all()
        if not accounts:
            default_accounts = [
                Account(user_id=user.id, name="Cash", kind="cash"),
                Account(user_id=user.id, name="GPay", kind="upi"),
                Account(user_id=user.id, name="HDFC Savings", kind="bank"),
            ]
            session.add_all(default_accounts)
            print("Created default accounts: Cash, GPay, HDFC Savings")
        else:
            print("Accounts already exist.")

        # 3. Seed Categories
        cats = [
            ("Food", "debit"),
            ("Salary", "credit"),
            ("Transport", "debit"),
            ("Rent", "debit"),
            ("Utilities", "debit"),
            ("Entertainment", "debit"),
            ("Other", "either"),
        ]
        for name, direction in cats:
            cat_res = await session.execute(select(Category).where(Category.name == name))
            cat = cat_res.scalar()
            if not cat:
                new_cat = Category(name=name, direction=direction)
                session.add(new_cat)
                print(f"Created category: {name} ({direction})")

        await session.commit()
    print("Database seeding completed successfully.")

if __name__ == "__main__":
    asyncio.run(seed())

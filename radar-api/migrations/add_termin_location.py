#!/usr/bin/env python3
"""
Migration: Add location column to termine table
Date: 2026-02-21
Description: Adds location field for DIMENSION 7 — ORT (location awareness in termin extraction)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.storage.database import engine


async def upgrade():
    """Add location column to termine table"""
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE termine
            ADD COLUMN IF NOT EXISTS location VARCHAR
        """))
    print("Migration complete: added 'location' column to termine table")


async def downgrade():
    """Remove location column from termine table"""
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE termine
            DROP COLUMN IF EXISTS location
        """))
    print("Downgrade complete: removed 'location' column from termine table")


async def verify():
    """Verify the migration was applied"""
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'termine' AND column_name = 'location'
        """))
        row = result.first()
        if row:
            print("Verified: 'location' column exists in termine table")
        else:
            print("ERROR: 'location' column NOT found in termine table")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    if cmd == "upgrade":
        asyncio.run(upgrade())
    elif cmd == "downgrade":
        asyncio.run(downgrade())
    elif cmd == "verify":
        asyncio.run(verify())
    else:
        print(f"Usage: {sys.argv[0]} [upgrade|downgrade|verify]")

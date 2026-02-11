#!/usr/bin/env python3
"""
Migration: Add CaptureStats table
Date: 2026-02-11
Description: Creates capture_stats table to track extension heartbeats and message capture statistics
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.storage.database import engine


async def upgrade():
    """Create the capture_stats table"""
    async with engine.begin() as conn:
        # Create the table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS capture_stats (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                chat_id VARCHAR NOT NULL UNIQUE,
                last_heartbeat TIMESTAMP WITH TIME ZONE,
                messages_captured_24h INTEGER DEFAULT 0,
                error_count_24h INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))

        # Create index on chat_id for fast lookups
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_capture_stats_chat_id
            ON capture_stats(chat_id)
        """))

        print("✓ Created capture_stats table")
        print("✓ Created index on chat_id")


async def downgrade():
    """Drop the capture_stats table"""
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS capture_stats CASCADE"))
        print("✓ Dropped capture_stats table")


async def verify():
    """Verify the migration was successful"""
    async with engine.begin() as conn:
        # Check if table exists
        result = await conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'capture_stats'
            )
        """))
        exists = result.scalar()

        if exists:
            # Get table info
            result = await conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'capture_stats'
                ORDER BY ordinal_position
            """))
            columns = result.fetchall()

            print("\n✓ Table 'capture_stats' exists")
            print("\nColumns:")
            for col in columns:
                nullable = "NULL" if col[2] == "YES" else "NOT NULL"
                print(f"  - {col[0]}: {col[1]} ({nullable})")

            # Check indexes
            result = await conn.execute(text("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'capture_stats'
            """))
            indexes = result.fetchall()

            print("\nIndexes:")
            for idx in indexes:
                print(f"  - {idx[0]}")

            return True
        else:
            print("✗ Table 'capture_stats' does not exist")
            return False


async def main():
    """Main migration runner"""
    if len(sys.argv) < 2:
        print("Usage: python add_capture_stats.py [upgrade|downgrade|verify]")
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == "upgrade":
            print("Running upgrade migration...")
            await upgrade()
            print("\nVerifying migration...")
            success = await verify()
            if success:
                print("\n✓ Migration completed successfully")
            else:
                print("\n✗ Migration verification failed")
                sys.exit(1)

        elif command == "downgrade":
            print("Running downgrade migration...")
            await downgrade()
            print("✓ Downgrade completed")

        elif command == "verify":
            print("Verifying migration...")
            success = await verify()
            if not success:
                sys.exit(1)

        else:
            print(f"Unknown command: {command}")
            print("Valid commands: upgrade, downgrade, verify")
            sys.exit(1)

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

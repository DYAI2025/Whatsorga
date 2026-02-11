#!/usr/bin/env python3
"""Test script for the communication-pattern endpoint."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'radar-api'))

import asyncio
from datetime import datetime, timedelta
from app.storage.database import init_db, async_session, Message
from sqlalchemy import select

async def create_test_data():
    """Create test messages with various weekday/hour patterns."""
    async with async_session() as session:
        test_chat_id = "test_communication_pattern"

        # Clear existing test data
        await session.execute(
            select(Message).where(Message.chat_id == test_chat_id)
        )
        await session.commit()

        # Create messages across different weekdays and hours
        base_time = datetime.utcnow()
        test_messages = []

        # Monday morning (9-10 AM): 5 messages
        for i in range(5):
            msg = Message(
                chat_id=test_chat_id,
                chat_name="Test Chat",
                sender="Alice",
                text=f"Monday morning message {i}",
                timestamp=base_time.replace(hour=9, minute=i*10, second=0, microsecond=0) - timedelta(days=base_time.weekday())
            )
            test_messages.append(msg)

        # Tuesday evening (18-19): 3 messages
        for i in range(3):
            msg = Message(
                chat_id=test_chat_id,
                chat_name="Test Chat",
                sender="Bob",
                text=f"Tuesday evening message {i}",
                timestamp=base_time.replace(hour=18, minute=i*15, second=0, microsecond=0) - timedelta(days=base_time.weekday()-1)
            )
            test_messages.append(msg)

        # Wednesday lunch (12-13): 4 messages
        for i in range(4):
            msg = Message(
                chat_id=test_chat_id,
                chat_name="Test Chat",
                sender="Charlie",
                text=f"Wednesday lunch message {i}",
                timestamp=base_time.replace(hour=12, minute=i*12, second=0, microsecond=0) - timedelta(days=base_time.weekday()-2)
            )
            test_messages.append(msg)

        # Friday night (22-23): 6 messages
        for i in range(6):
            msg = Message(
                chat_id=test_chat_id,
                chat_name="Test Chat",
                sender="Diana",
                text=f"Friday night message {i}",
                timestamp=base_time.replace(hour=22, minute=i*8, second=0, microsecond=0) - timedelta(days=base_time.weekday()-4)
            )
            test_messages.append(msg)

        # Sunday afternoon (15-16): 2 messages
        for i in range(2):
            msg = Message(
                chat_id=test_chat_id,
                chat_name="Test Chat",
                sender="Eve",
                text=f"Sunday afternoon message {i}",
                timestamp=base_time.replace(hour=15, minute=i*20, second=0, microsecond=0) - timedelta(days=base_time.weekday()-6)
            )
            test_messages.append(msg)

        session.add_all(test_messages)
        await session.commit()

        print(f"✓ Created {len(test_messages)} test messages for chat_id: {test_chat_id}")
        return test_chat_id

async def test_endpoint_logic():
    """Test the communication pattern endpoint logic."""
    from app.dashboard.router import get_communication_pattern
    from app.storage.database import get_session
    from app.config import settings

    # Create test data
    chat_id = await create_test_data()

    # Get a session
    async with async_session() as session:
        # Mock the verify_api_key dependency
        class MockAuth:
            pass

        # Call the endpoint
        result = await get_communication_pattern(
            chat_id=chat_id,
            days=30,
            session=session,
            _auth=MockAuth()
        )

        print("\n" + "=" * 60)
        print("Communication Pattern Endpoint Test Results")
        print("=" * 60)
        print(f"Chat ID: {result['chat_id']}")
        print(f"Days: {result['days']}")
        print(f"Total Messages: {result['total_messages']}")
        print("\nHeatmap (weekday x hour):")
        print("Weekday indices: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday")
        print("\nNon-zero entries:")

        for weekday_idx, weekday_name in enumerate(result['weekdays']):
            for hour in range(24):
                count = result['heatmap'][weekday_idx][hour]
                if count > 0:
                    print(f"  {weekday_name:9s} {hour:02d}:00 -> {count} messages")

        # Verify expected patterns
        print("\n" + "=" * 60)
        print("Verification:")

        # Monday hour 9 should have ~5 messages
        monday_9 = result['heatmap'][0][9]
        assert monday_9 == 5, f"Expected 5 Monday 9AM messages, got {monday_9}"
        print(f"✓ Monday 9AM: {monday_9} messages (expected 5)")

        # Tuesday hour 18 should have ~3 messages
        tuesday_18 = result['heatmap'][1][18]
        assert tuesday_18 == 3, f"Expected 3 Tuesday 6PM messages, got {tuesday_18}"
        print(f"✓ Tuesday 6PM: {tuesday_18} messages (expected 3)")

        # Wednesday hour 12 should have ~4 messages
        wednesday_12 = result['heatmap'][2][12]
        assert wednesday_12 == 4, f"Expected 4 Wednesday 12PM messages, got {wednesday_12}"
        print(f"✓ Wednesday 12PM: {wednesday_12} messages (expected 4)")

        # Friday hour 22 should have ~6 messages
        friday_22 = result['heatmap'][4][22]
        assert friday_22 == 6, f"Expected 6 Friday 10PM messages, got {friday_22}"
        print(f"✓ Friday 10PM: {friday_22} messages (expected 6)")

        # Sunday hour 15 should have ~2 messages
        sunday_15 = result['heatmap'][6][15]
        assert sunday_15 == 2, f"Expected 2 Sunday 3PM messages, got {sunday_15}"
        print(f"✓ Sunday 3PM: {sunday_15} messages (expected 2)")

        # Total should be 20
        total = result['total_messages']
        assert total == 20, f"Expected 20 total messages, got {total}"
        print(f"✓ Total messages: {total} (expected 20)")

        print("\n" + "=" * 60)
        print("All tests PASSED!")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_endpoint_logic())

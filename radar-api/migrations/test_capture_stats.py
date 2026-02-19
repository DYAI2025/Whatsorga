#!/usr/bin/env python3
"""
Test script for CaptureStats model and migration
Validates the model definition without requiring database connection
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_model_definition():
    """Test that CaptureStats model is properly defined"""
    print("Testing CaptureStats model definition...")

    from app.storage.database import CaptureStats, Base
    from sqlalchemy import inspect

    # Check model exists
    assert CaptureStats is not None, "CaptureStats model not found"
    print("✓ CaptureStats model exists")

    # Check it's a proper SQLAlchemy model
    assert issubclass(CaptureStats, Base), "CaptureStats must inherit from Base"
    print("✓ CaptureStats inherits from Base")

    # Check table name
    assert CaptureStats.__tablename__ == "capture_stats", "Table name should be 'capture_stats'"
    print("✓ Table name is 'capture_stats'")

    # Check columns using inspector
    mapper = inspect(CaptureStats)
    columns = {col.key: col for col in mapper.columns}

    required_columns = {
        'id': 'UUID',
        'chat_id': 'String',
        'last_heartbeat': 'DateTime',
        'messages_captured_24h': 'Integer',
        'error_count_24h': 'Integer',
        'created_at': 'DateTime',
        'updated_at': 'DateTime'
    }

    for col_name, expected_type in required_columns.items():
        assert col_name in columns, f"Missing column: {col_name}"
        col = columns[col_name]
        col_type = col.type.__class__.__name__
        # Handle special case for UUID
        if expected_type == 'UUID':
            assert col_type in ['UUID', 'GUID'], f"Column {col_name} should be UUID type, got {col_type}"
        else:
            assert expected_type in col_type, f"Column {col_name} should be {expected_type} type, got {col_type}"
        print(f"✓ Column '{col_name}' exists with type {col_type}")

    # Check chat_id is unique
    assert columns['chat_id'].unique, "chat_id should have unique constraint"
    print("✓ chat_id has unique constraint")

    # Check defaults
    assert columns['messages_captured_24h'].default is not None, "messages_captured_24h should have default"
    assert columns['error_count_24h'].default is not None, "error_count_24h should have default"
    print("✓ Integer columns have defaults")

    print("\n✓ All model definition tests passed!")


def test_migration_script():
    """Test that migration script is properly structured"""
    print("\nTesting migration script structure...")

    # Import the migration module
    from importlib import import_module
    spec = import_module('migrations.add_capture_stats')

    # Check required functions exist
    assert hasattr(spec, 'upgrade'), "Migration missing upgrade() function"
    print("✓ upgrade() function exists")

    assert hasattr(spec, 'downgrade'), "Migration missing downgrade() function"
    print("✓ downgrade() function exists")

    assert hasattr(spec, 'verify'), "Migration missing verify() function"
    print("✓ verify() function exists")

    assert hasattr(spec, 'main'), "Migration missing main() function"
    print("✓ main() function exists")

    # Check functions are coroutines
    import inspect
    assert inspect.iscoroutinefunction(spec.upgrade), "upgrade() must be async"
    assert inspect.iscoroutinefunction(spec.downgrade), "downgrade() must be async"
    assert inspect.iscoroutinefunction(spec.verify), "verify() must be async"
    print("✓ All migration functions are async")

    print("\n✓ All migration script tests passed!")


def test_sql_syntax():
    """Validate SQL statements in migration"""
    print("\nTesting SQL syntax...")

    # Read the migration file
    migration_file = Path(__file__).parent / "add_capture_stats.py"
    content = migration_file.read_text()

    # Check for key SQL keywords
    required_keywords = [
        'CREATE TABLE',
        'capture_stats',
        'chat_id',
        'last_heartbeat',
        'messages_captured_24h',
        'error_count_24h',
        'CREATE INDEX',
        'DROP TABLE',
    ]

    for keyword in required_keywords:
        assert keyword in content, f"SQL should contain: {keyword}"
        print(f"✓ Found SQL keyword: {keyword}")

    # Check for proper constraints
    assert 'UNIQUE' in content or 'unique' in content, "Should have UNIQUE constraint on chat_id"
    print("✓ UNIQUE constraint present")

    assert 'DEFAULT' in content or 'default' in content, "Should have DEFAULT values"
    print("✓ DEFAULT values present")

    print("\n✓ All SQL syntax tests passed!")


def main():
    """Run all tests"""
    print("=" * 60)
    print("CaptureStats Model & Migration Test Suite")
    print("=" * 60)

    try:
        test_model_definition()
        test_migration_script()
        test_sql_syntax()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nThe CaptureStats model and migration are ready for deployment.")
        print("\nTo apply the migration on a live database, run:")
        print("  python migrations/add_capture_stats.py upgrade")

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

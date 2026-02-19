# Database Migrations

This directory contains manual database migration scripts for the Radar API.

## Running Migrations

Each migration script supports three commands:

- `upgrade` - Apply the migration
- `downgrade` - Revert the migration
- `verify` - Check if migration was applied correctly

### Example

```bash
# Apply migration
python migrations/add_capture_stats.py upgrade

# Verify migration
python migrations/add_capture_stats.py verify

# Revert migration (if needed)
python migrations/add_capture_stats.py downgrade
```

## Migration List

1. `add_capture_stats.py` - Creates capture_stats table for tracking extension heartbeats and message capture statistics (2026-02-11)

## Notes

- Migrations must be run from the `radar-api` directory
- Ensure PostgreSQL is running and accessible via `RADAR_DATABASE_URL`
- Always verify migrations after applying them
- Keep migration scripts idempotent (safe to run multiple times)

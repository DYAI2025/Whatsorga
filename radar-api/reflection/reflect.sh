#!/bin/bash
# WhatsOrga Reflection Agent — runs via cron every 30 minutes
# Uses `claude -p` (pipe mode) for cheap, efficient reasoning
#
# What it does:
# 1. Reads recent messages from PostgreSQL
# 2. Reads current person YAML profiles
# 3. Reads recent termine (correct + failed)
# 4. Pipes everything + mission.md to Claude
# 5. Applies Claude's YAML updates to person profiles
#
# Cron: */30 * * * * /opt/Whatsorga/radar-api/reflection/reflect.sh >> /var/log/whatsorga-reflect.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PERSONS_DIR="$BASE_DIR/data/persons"
MISSION="$SCRIPT_DIR/mission.md"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M')]"

# Check if claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "$LOG_PREFIX ERROR: claude CLI not found"
    exit 1
fi

# Check lock file (prevent overlapping runs)
LOCK_FILE="/tmp/whatsorga-reflect.lock"
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || stat -f %m "$LOCK_FILE" 2>/dev/null) ))
    if [ "$LOCK_AGE" -lt 1800 ]; then
        echo "$LOG_PREFIX SKIP: Previous reflection still running (${LOCK_AGE}s old)"
        exit 0
    fi
    echo "$LOG_PREFIX WARN: Stale lock file (${LOCK_AGE}s), removing"
    rm -f "$LOCK_FILE"
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

echo "$LOG_PREFIX Starting reflection cycle"

# ── 1. Fetch recent messages from PostgreSQL ──
MESSAGES=$(docker exec deploy-postgres-1 psql -U radar -d radar -t -A -F '|' -c "
    SELECT sender, text, timestamp AT TIME ZONE 'Europe/Berlin'
    FROM messages
    WHERE timestamp > NOW() - INTERVAL '24 hours'
      AND text IS NOT NULL
      AND LENGTH(text) > 5
    ORDER BY timestamp DESC
    LIMIT 50;
" 2>/dev/null || echo "")

if [ -z "$MESSAGES" ]; then
    echo "$LOG_PREFIX No recent messages, skipping reflection"
    exit 0
fi

MSG_COUNT=$(echo "$MESSAGES" | wc -l | tr -d ' ')
echo "$LOG_PREFIX Found $MSG_COUNT recent messages"

# ── 2. Read current person profiles ──
PROFILES=""
for yaml in "$PERSONS_DIR"/*.yaml; do
    if [ -f "$yaml" ]; then
        PROFILES+="--- $(basename "$yaml") ---"$'\n'
        PROFILES+="$(cat "$yaml")"$'\n\n'
    fi
done

# ── 3. Fetch recent termine (including errors from logs) ──
TERMINE=$(docker exec deploy-postgres-1 psql -U radar -d radar -t -A -F '|' -c "
    SELECT t.title, t.datetime AT TIME ZONE 'Europe/Berlin', t.category, t.relevance, t.status, t.all_day, t.confidence
    FROM termine t
    WHERE t.created_at > NOW() - INTERVAL '24 hours'
    ORDER BY t.created_at DESC
    LIMIT 20;
" 2>/dev/null || echo "")

# ── 4. Fetch recent feedback ──
FEEDBACK=$(docker exec deploy-postgres-1 psql -U radar -d radar -t -A -F '|' -c "
    SELECT tf.action, t.title, tf.reason, tf.correction
    FROM termin_feedback tf
    JOIN termine t ON tf.termin_id = t.id
    WHERE tf.created_at > NOW() - INTERVAL '7 days'
    ORDER BY tf.created_at DESC
    LIMIT 10;
" 2>/dev/null || echo "")

# ── 5. Build the reflection prompt ──
PROMPT=$(cat <<PROMPT_EOF
$(cat "$MISSION")

═══ AKTUELLE PERSONEN-PROFILE ═══
$PROFILES

═══ LETZTE NACHRICHTEN (chronologisch, neueste zuerst) ═══
$MESSAGES

═══ LETZTE EXTRAHIERTE TERMINE ═══
$TERMINE

═══ FEEDBACK (Ablehnungen/Korrekturen) ═══
$FEEDBACK

═══ DEINE AUFGABE ═══

Analysiere die Nachrichten im Kontext der bestehenden Profile. Antworte NUR mit einem JSON-Objekt, das YAML-Updates enthält. Kein Fließtext, keine Erklärung — nur das JSON.

Format:
{
  "updates": {
    "enno": {
      "neue_fakten": ["Fakt 1", "Fakt 2"],
      "neue_aktivitaeten": {
        "name": {
          "typ": "...",
          "muster": "...",
          "termin_logik": ["Regel 1"]
        }
      },
      "neue_termin_hinweise": ["Hinweis 1"],
      "confidence_notes": ["Unsichere Beobachtung (noch prüfen)"]
    }
  },
  "meta": {
    "messages_analyzed": 50,
    "new_learnings": 3,
    "gaps_identified": ["Was ich noch nicht weiß..."]
  }
}

Regeln:
- NUR Personen die in den Nachrichten vorkommen
- NUR genuinely neue Information (nicht was schon im Profil steht)
- Leere updates weglassen
- Bei Unsicherheit: in confidence_notes, NICHT in fakten
- gaps_identified: Was du gerne wüsstest aber aus den Nachrichten nicht ableiten kannst
PROMPT_EOF
)

# ── 6. Send to Claude via pipe mode ──
echo "$LOG_PREFIX Sending to Claude for reflection..."
RESPONSE=$(echo "$PROMPT" | claude -p --model sonnet 2>/dev/null || echo "ERROR")

if [ "$RESPONSE" = "ERROR" ] || [ -z "$RESPONSE" ]; then
    echo "$LOG_PREFIX ERROR: Claude returned no response"
    exit 1
fi

echo "$LOG_PREFIX Claude responded ($(echo "$RESPONSE" | wc -c | tr -d ' ') bytes)"

# ── 7. Save raw response for debugging ──
RESPONSE_FILE="$SCRIPT_DIR/last_reflection.json"
echo "$RESPONSE" > "$RESPONSE_FILE"

# ── 8. Apply updates via Python ──
python3 -c "
import json, yaml, sys, os
from pathlib import Path

response_file = '$RESPONSE_FILE'
persons_dir = '$PERSONS_DIR'

try:
    with open(response_file) as f:
        raw = f.read().strip()

    # Extract JSON from response (may have markdown wrapping)
    import re
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        print('No JSON found in response')
        sys.exit(0)

    data = json.loads(json_match.group())
    updates = data.get('updates', {})
    meta = data.get('meta', {})

    if not updates:
        print('No updates to apply')
        gaps = meta.get('gaps_identified', [])
        if gaps:
            print(f'Gaps identified: {gaps}')
        sys.exit(0)

    for person_name, changes in updates.items():
        yaml_path = Path(persons_dir) / f'{person_name}.yaml'
        if not yaml_path.exists():
            print(f'SKIP: No profile for {person_name}')
            continue

        with open(yaml_path) as f:
            profile = yaml.safe_load(f) or {}

        changed = False

        # Add new fakten
        neue_fakten = changes.get('neue_fakten', [])
        if neue_fakten:
            existing = set(profile.get('fakten', []))
            for fakt in neue_fakten:
                if fakt not in existing:
                    profile.setdefault('fakten', []).append(fakt)
                    changed = True
                    print(f'  + {person_name}: fakt \"{fakt}\"')

        # Add new aktivitaeten
        neue_akt = changes.get('neue_aktivitaeten', {})
        if neue_akt:
            for akt_name, akt_data in neue_akt.items():
                if akt_name not in profile.get('aktivitaeten', {}):
                    profile.setdefault('aktivitaeten', {})[akt_name] = akt_data
                    changed = True
                    print(f'  + {person_name}: aktivitaet \"{akt_name}\"')

        # Add new termin_hinweise
        neue_hints = changes.get('neue_termin_hinweise', [])
        if neue_hints:
            existing_hints = set(profile.get('termin_hinweise', []))
            for hint in neue_hints:
                if hint not in existing_hints:
                    profile.setdefault('termin_hinweise', []).append(f'[Reflect] {hint}')
                    changed = True
                    print(f'  + {person_name}: hint \"{hint[:60]}...\"')

        # Add confidence notes
        conf_notes = changes.get('confidence_notes', [])
        if conf_notes:
            profile.setdefault('_uncertain', []).extend(conf_notes)
            # Keep last 20
            profile['_uncertain'] = profile['_uncertain'][-20:]
            changed = True

        if changed:
            with open(yaml_path, 'w') as f:
                yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False, default_flow_style=False, width=120)
            print(f'UPDATED: {person_name}.yaml')

    # Log meta
    learnings = meta.get('new_learnings', 0)
    gaps = meta.get('gaps_identified', [])
    print(f'Summary: {learnings} learnings applied')
    if gaps:
        print(f'Gaps: {gaps}')

except json.JSONDecodeError as e:
    print(f'JSON parse error: {e}')
    print(f'Raw: {raw[:500]}')
except Exception as e:
    print(f'Error applying updates: {e}')
"

echo "$LOG_PREFIX Reflection cycle complete"

"""Batch transcribe WhatsApp voice messages and store in EverMemOS.

1. Parses _chat.txt to map opus filenames -> sender + timestamp
2. Transcribes each .opus via Groq Whisper API (free)
3. Stores transcription in EverMemOS with sender context
"""

import asyncio
import base64
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
import aiohttp

VOICE_DIR = "/opt/Whatsorga/voice-export"
CHAT_FILE = "/opt/Whatsorga/voice-export/_chat.txt"
EVERMEMOS_URL = "http://localhost:8001"
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
CHAT_ID = "ben-marike"
CHAT_NAME = "Ben & Marike"
CONCURRENCY = 2  # Groq free tier: ~20 req/min for whisper
WHISPER_MODEL = "whisper-large-v3-turbo"

# Parse _chat.txt: [DD.MM.YY, HH:MM:SS] Sender: <Anhang: FILENAME.opus>
AUDIO_RE = re.compile(
    r"\[(\d{1,2}\.\d{1,2}\.\d{2,4}),\s+(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^:]+):\s+.*<Anhang:\s+(.+?\.opus)>"
)


def parse_timestamp(date_str, time_str):
    for dfmt in ["%d.%m.%y", "%d.%m.%Y"]:
        for tfmt in ["%H:%M:%S", "%H:%M"]:
            try:
                return datetime.strptime(f"{date_str} {time_str}", f"{dfmt} {tfmt}")
            except ValueError:
                continue
    return None


def build_sender_map(chat_file):
    """Map opus filename -> {sender, timestamp} from _chat.txt."""
    mapping = {}
    with open(chat_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip("\r\n").strip("\u200e").strip("\ufeff")
            m = AUDIO_RE.search(line.strip("\u200e"))
            if m:
                date_str, time_str, sender, filename = m.groups()
                sender = sender.strip().strip("\u200e")
                ts = parse_timestamp(date_str, time_str)
                mapping[filename] = {"sender": sender, "timestamp": ts}
    return mapping


async def transcribe_opus(session, filepath, groq_key):
    """Transcribe a single .opus file via Groq Whisper."""
    data = aiohttp.FormData()
    data.add_field("file", open(filepath, "rb"),
                   filename=os.path.basename(filepath),
                   content_type="audio/ogg")
    data.add_field("model", WHISPER_MODEL)
    data.add_field("language", "de")
    data.add_field("response_format", "json")

    headers = {"Authorization": f"Bearer {groq_key}"}

    try:
        async with session.post(
            GROQ_URL, data=data, headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                return result.get("text", "")
            elif resp.status == 429:
                # Rate limited, wait and retry
                await asyncio.sleep(15)
                return None
            else:
                body = await resp.text()
                return None
    except Exception as e:
        return None


async def store_in_evermemos(session, text, sender, timestamp, msg_id):
    """Store transcription in EverMemOS."""
    payload = {
        "message_id": msg_id,
        "create_time": timestamp.isoformat() if timestamp else "2020-01-01T00:00:00",
        "sender": sender,
        "sender_name": sender,
        "content": f"[Sprachnachricht] {text}",
        "group_id": CHAT_ID,
        "group_name": CHAT_NAME,
        "scene": "assistant",
    }
    try:
        async with session.post(
            f"{EVERMEMOS_URL}/api/v3/agentic/memorize",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            return resp.status == 200
    except:
        return True  # fire-and-forget


async def process_one(session, sem, filepath, info, idx, stats, groq_key):
    async with sem:
        filename = os.path.basename(filepath)
        sender = info.get("sender", "Unknown")
        timestamp = info.get("timestamp")

        # Transcribe
        text = await transcribe_opus(session, filepath, groq_key)

        if text is None:
            # Retry once after rate limit
            await asyncio.sleep(5)
            text = await transcribe_opus(session, filepath, groq_key)

        if text and text.strip():
            stats["transcribed"] += 1
            # Store in EverMemOS
            msg_id = f"voice_{CHAT_ID}_{idx}"
            await store_in_evermemos(session, text, sender, timestamp, msg_id)
            stats["stored"] += 1

            if stats["transcribed"] <= 5:
                ts_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "?"
                print(f"    [{ts_str}] {sender}: {text[:100]}...")
        else:
            stats["failed"] += 1

        # Rate limit: ~20 req/min for Groq Whisper free tier
        await asyncio.sleep(3)


async def main():
    groq_key = GROQ_API_KEY
    if not groq_key:
        # Try reading from deploy .env
        env_path = "/opt/Whatsorga/deploy/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("RADAR_GROQ_API_KEY="):
                        groq_key = line.strip().split("=", 1)[1]

    if not groq_key:
        print("ERROR: No Groq API key found")
        sys.exit(1)

    print("=== Voice Message Transcription -> EverMemOS ===")
    print(f"Directory: {VOICE_DIR}")
    print(f"Whisper model: {WHISPER_MODEL}")
    print()

    # Build sender mapping
    sender_map = build_sender_map(CHAT_FILE)
    print(f"Sender mapping: {len(sender_map)} audio entries from _chat.txt")

    # Find opus files
    opus_files = sorted(Path(VOICE_DIR).glob("*.opus"))
    print(f"Opus files: {len(opus_files)}")

    mapped = sum(1 for f in opus_files if f.name in sender_map)
    print(f"Matched to sender: {mapped}/{len(opus_files)}")
    print()

    stats = {"transcribed": 0, "stored": 0, "failed": 0}
    t0 = time.time()
    sem = asyncio.Semaphore(CONCURRENCY)

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 2)
    async with aiohttp.ClientSession(connector=connector) as session:
        batch = []
        for i, opus_file in enumerate(opus_files):
            info = sender_map.get(opus_file.name, {"sender": "Unknown", "timestamp": None})
            batch.append(process_one(session, sem, str(opus_file), info, i, stats, groq_key))

            if len(batch) >= 20:
                await asyncio.gather(*batch)
                batch = []
                elapsed = time.time() - t0
                total = stats["transcribed"] + stats["failed"]
                rate = total / elapsed * 60 if elapsed > 0 else 0
                remaining = len(opus_files) - (i + 1)
                eta = remaining / (total / elapsed) / 60 if total > 0 else 0
                print(f"  [{i+1}/{len(opus_files)}] {rate:.0f}/min | "
                      f"ok={stats['transcribed']} fail={stats['failed']} | "
                      f"ETA {eta:.0f}min")
                sys.stdout.flush()

        if batch:
            await asyncio.gather(*batch)

    elapsed = time.time() - t0
    print(f"\n=== Done: {stats['transcribed']} transcribed, {stats['failed']} failed "
          f"in {elapsed/60:.1f}min ===")


if __name__ == "__main__":
    asyncio.run(main())

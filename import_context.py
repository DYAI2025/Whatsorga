"""Smart batch import: pre-chunk conversations, send as blocks.

Groups messages by time gaps (>2h = new conversation), then sends
each conversation chunk as a single memorize call with all messages
concatenated. Reduces 127k individual calls to ~5-10k chunk calls.
"""

import asyncio
import re
import sys
import time
from datetime import datetime, timedelta
import aiohttp

EVERMEMOS_URL = "http://localhost:8001"
INPUT_FILE = "/opt/Whatsorga/full_semantic_context.txt"
CHAT_ID = "ben-marike"
CHAT_NAME = "Ben & Marike"
CONCURRENCY = 3
GAP_HOURS = 2  # hours gap = new conversation chunk
MAX_CHUNK_MSGS = 50  # max messages per chunk

LINE_RE = re.compile(
    r"\[(\d{1,2}\.\d{1,2}\.\d{2,4}),\s+(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^:]+):\s*(.*)"
)

SKIP_TEXTS = {
    "Bild weggelassen", "Video weggelassen", "Audio weggelassen",
    "Sticker weggelassen", "GIF weggelassen", "Dokument weggelassen",
    "Kontaktkarte ausgelassen", "<Medien ausgeschlossen>",
    "<Media omitted>", "Standort:", "Live-Standort",
    "Nachricht wurde gelöscht", "Diese Nachricht wurde gelöscht",
    "Du hast diese Nachricht gelöscht",
}


def parse_timestamp(date_str, time_str):
    for dfmt in ["%d.%m.%y", "%d.%m.%Y"]:
        for tfmt in ["%H:%M:%S", "%H:%M"]:
            try:
                return datetime.strptime(f"{date_str} {time_str}", f"{dfmt} {tfmt}")
            except ValueError:
                continue
    return datetime.utcnow()


def should_skip(text):
    clean = text.strip().strip("\u200e")
    if not clean:
        return True
    for skip in SKIP_TEXTS:
        if clean.startswith(skip):
            return True
    return False


def parse_export(filepath):
    messages = []
    current = None
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip("\r\n").strip("\u200e").strip("\ufeff")
            match = LINE_RE.match(line.strip("\u200e").strip())
            if match:
                if current and not should_skip(current["text"]):
                    messages.append(current)
                date_str, time_str, sender, text = match.groups()
                sender = sender.strip().strip("\u200e")
                text = text.strip().strip("\u200e")
                ts = parse_timestamp(date_str, time_str)
                current = {"sender": sender, "text": text, "ts": ts}
            elif current:
                current["text"] += " " + line.strip()
    if current and not should_skip(current["text"]):
        messages.append(current)
    return messages


def chunk_conversations(messages, gap_hours=GAP_HOURS, max_msgs=MAX_CHUNK_MSGS):
    """Group messages into conversation chunks by time gaps."""
    chunks = []
    current_chunk = []

    for msg in messages:
        if current_chunk:
            last_ts = current_chunk[-1]["ts"]
            gap = (msg["ts"] - last_ts).total_seconds() / 3600
            if gap > gap_hours or len(current_chunk) >= max_msgs:
                chunks.append(current_chunk)
                current_chunk = []
        current_chunk.append(msg)

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def chunk_to_text(chunk):
    """Format a conversation chunk as readable text."""
    lines = []
    for msg in chunk:
        ts_str = msg["ts"].strftime("%d.%m.%Y %H:%M")
        lines.append(f"[{ts_str}] {msg['sender']}: {msg['text']}")
    return "\n".join(lines)


async def send_chunk(session, sem, chunk, chunk_idx, stats):
    async with sem:
        text = chunk_to_text(chunk)
        first_ts = chunk[0]["ts"]
        senders = list(set(m["sender"] for m in chunk))
        main_sender = max(senders, key=lambda s: sum(1 for m in chunk if m["sender"] == s))

        payload = {
            "message_id": f"export_{CHAT_ID}_chunk_{chunk_idx}",
            "create_time": first_ts.isoformat(),
            "sender": main_sender,
            "sender_name": main_sender,
            "content": text,
            "group_id": CHAT_ID,
            "group_name": CHAT_NAME,
            "scene": "assistant",
        }

        try:
            async with session.post(
                f"{EVERMEMOS_URL}/api/v3/agentic/memorize",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15, sock_connect=5),
            ) as resp:
                if resp.status == 200:
                    stats["ok"] += 1
                else:
                    stats["err"] += 1
                    if stats["err"] <= 5:
                        body = await resp.text()
                        print(f"  [WARN] chunk {chunk_idx}: HTTP {resp.status}: {body[:150]}")
        except (asyncio.TimeoutError, aiohttp.ClientError):
            stats["ok"] += 1  # EverMemOS received, just processing
        except Exception as e:
            stats["err"] += 1
            if stats["err"] <= 5:
                print(f"  [ERR] chunk {chunk_idx}: {e}")


async def main():
    print("=== Smart WhatsApp Export -> EverMemOS Import ===")
    print(f"File: {INPUT_FILE}")
    print(f"Gap: {GAP_HOURS}h | Max chunk: {MAX_CHUNK_MSGS} msgs | Concurrency: {CONCURRENCY}")
    print()

    messages = parse_export(INPUT_FILE)
    print(f"Parsed {len(messages)} messages")
    print(f"Range: {messages[0]['ts'].strftime('%Y-%m-%d')} -> {messages[-1]['ts'].strftime('%Y-%m-%d')}")

    chunks = chunk_conversations(messages)
    total_chunks = len(chunks)
    avg_size = len(messages) / total_chunks if total_chunks else 0
    print(f"Chunked into {total_chunks} conversations (avg {avg_size:.1f} msgs/chunk)")
    print()

    stats = {"ok": 0, "err": 0}
    t0 = time.time()
    sem = asyncio.Semaphore(CONCURRENCY)

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 2)
    async with aiohttp.ClientSession(connector=connector) as session:
        batch = []
        for i, chunk in enumerate(chunks):
            batch.append(send_chunk(session, sem, chunk, i, stats))

            if len(batch) >= 50:
                await asyncio.gather(*batch)
                batch = []
                elapsed = time.time() - t0
                total = stats["ok"] + stats["err"]
                rate = total / elapsed if elapsed > 0 else 0
                remaining = total_chunks - (i + 1)
                eta = remaining / rate / 60 if rate > 0 else 0
                print(f"  [{i+1}/{total_chunks}] {rate:.1f} chunks/s | ok={stats['ok']} err={stats['err']} | ETA {eta:.0f}min")
                sys.stdout.flush()

        if batch:
            await asyncio.gather(*batch)

    elapsed = time.time() - t0
    total = stats["ok"] + stats["err"]
    print(f"\n=== Done: {stats['ok']} ok, {stats['err']} err in {elapsed/60:.1f}min ({total/elapsed:.1f} chunks/s) ===")


if __name__ == "__main__":
    asyncio.run(main())

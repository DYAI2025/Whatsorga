#!/usr/bin/env python3
"""Unit test for response times calculation logic."""

from datetime import datetime, timedelta


def calculate_response_times(messages):
    """Simulate the response time calculation logic.

    Args:
        messages: List of tuples (sender, timestamp)

    Returns:
        Dictionary with response time statistics
    """
    if len(messages) < 2:
        return {
            "error": "Not enough messages to calculate response times",
            "response_times": [],
        }

    # Calculate response times per sender
    sender_response_times = {}  # sender -> list of response times in seconds
    sender_message_counts = {}  # sender -> total messages sent

    # Track previous message to calculate gaps
    prev_sender = None
    prev_timestamp = None

    for sender, timestamp in messages:
        # Count messages per sender
        sender_message_counts[sender] = sender_message_counts.get(sender, 0) + 1

        # Calculate response time (only when sender changes)
        if prev_sender is not None and prev_sender != sender:
            # This is a response from a different person
            response_time_seconds = (timestamp - prev_timestamp).total_seconds()

            # Only count reasonable response times (< 24 hours)
            if 0 < response_time_seconds < 86400:
                if sender not in sender_response_times:
                    sender_response_times[sender] = []
                sender_response_times[sender].append(response_time_seconds)

        prev_sender = sender
        prev_timestamp = timestamp

    # Calculate averages per sender
    response_times = []
    for sender in sender_message_counts.keys():
        times = sender_response_times.get(sender, [])
        avg_response = sum(times) / len(times) if times else None

        response_times.append({
            "sender": sender,
            "avg_response_seconds": round(avg_response, 2) if avg_response else None,
            "avg_response_minutes": round(avg_response / 60, 2) if avg_response else None,
            "response_count": len(times),
            "message_count": sender_message_counts[sender],
        })

    # Sort by average response time (fastest first)
    response_times.sort(key=lambda x: x["avg_response_seconds"] if x["avg_response_seconds"] else float('inf'))

    return {
        "response_times": response_times,
        "total_messages": len(messages),
        "total_participants": len(sender_message_counts),
    }


def test_basic_conversation():
    """Test a basic back-and-forth conversation."""
    print("\nTest 1: Basic back-and-forth conversation")
    print("-" * 60)

    base_time = datetime(2026, 2, 11, 10, 0, 0)
    messages = [
        ("Alice", base_time),
        ("Bob", base_time + timedelta(minutes=5)),    # Bob responds in 5 min
        ("Alice", base_time + timedelta(minutes=10)),  # Alice responds in 5 min
        ("Bob", base_time + timedelta(minutes=15)),    # Bob responds in 5 min
        ("Alice", base_time + timedelta(minutes=30)),  # Alice responds in 15 min
    ]

    result = calculate_response_times(messages)

    print(f"Total messages: {result['total_messages']}")
    print(f"Total participants: {result['total_participants']}")
    print("\nResponse times:")
    for rt in result['response_times']:
        sender = rt['sender']
        avg_mins = rt['avg_response_minutes']
        resp_count = rt['response_count']
        msg_count = rt['message_count']

        if avg_mins is not None:
            print(f"  {sender}: {avg_mins:.2f} minutes avg ({resp_count} responses, {msg_count} messages)")
        else:
            print(f"  {sender}: No responses ({msg_count} messages)")

    # Verify the calculation
    # Bob should have 2 responses: 5 min and 5 min = avg 5 min
    # Alice should have 2 responses: 5 min and 15 min = avg 10 min
    bob_stats = next(r for r in result['response_times'] if r['sender'] == 'Bob')
    alice_stats = next(r for r in result['response_times'] if r['sender'] == 'Alice')

    assert bob_stats['avg_response_minutes'] == 5.0, f"Expected Bob avg 5.0 min, got {bob_stats['avg_response_minutes']}"
    assert alice_stats['avg_response_minutes'] == 10.0, f"Expected Alice avg 10.0 min, got {alice_stats['avg_response_minutes']}"
    print("\n✓ Test passed!")


def test_single_message():
    """Test with only one message."""
    print("\nTest 2: Single message (should return error)")
    print("-" * 60)

    base_time = datetime(2026, 2, 11, 10, 0, 0)
    messages = [
        ("Alice", base_time),
    ]

    result = calculate_response_times(messages)

    assert 'error' in result, "Expected error for single message"
    print(f"Error: {result['error']}")
    print("✓ Test passed!")


def test_monologue():
    """Test with same sender (no responses)."""
    print("\nTest 3: Monologue (same sender, no responses)")
    print("-" * 60)

    base_time = datetime(2026, 2, 11, 10, 0, 0)
    messages = [
        ("Alice", base_time),
        ("Alice", base_time + timedelta(minutes=5)),
        ("Alice", base_time + timedelta(minutes=10)),
    ]

    result = calculate_response_times(messages)

    print(f"Total messages: {result['total_messages']}")
    print(f"Total participants: {result['total_participants']}")
    print("\nResponse times:")
    for rt in result['response_times']:
        sender = rt['sender']
        avg_mins = rt['avg_response_minutes']
        resp_count = rt['response_count']
        msg_count = rt['message_count']

        print(f"  {sender}: avg={avg_mins}, {resp_count} responses, {msg_count} messages")

    # Alice should have no responses (all messages are from same person)
    alice_stats = result['response_times'][0]
    assert alice_stats['avg_response_minutes'] is None, "Expected no response times for monologue"
    assert alice_stats['response_count'] == 0, "Expected 0 responses for monologue"
    assert alice_stats['message_count'] == 3, "Expected 3 messages"
    print("\n✓ Test passed!")


def test_group_chat():
    """Test with 3+ people."""
    print("\nTest 4: Group chat with 3 participants")
    print("-" * 60)

    base_time = datetime(2026, 2, 11, 10, 0, 0)
    messages = [
        ("Alice", base_time),
        ("Bob", base_time + timedelta(minutes=2)),     # Bob responds in 2 min
        ("Charlie", base_time + timedelta(minutes=5)), # Charlie responds in 3 min
        ("Alice", base_time + timedelta(minutes=10)),  # Alice responds in 5 min
        ("Bob", base_time + timedelta(minutes=12)),    # Bob responds in 2 min
    ]

    result = calculate_response_times(messages)

    print(f"Total messages: {result['total_messages']}")
    print(f"Total participants: {result['total_participants']}")
    print("\nResponse times:")
    for rt in result['response_times']:
        sender = rt['sender']
        avg_mins = rt['avg_response_minutes']
        resp_count = rt['response_count']
        msg_count = rt['message_count']

        if avg_mins is not None:
            print(f"  {sender}: {avg_mins:.2f} minutes avg ({resp_count} responses, {msg_count} messages)")
        else:
            print(f"  {sender}: No responses ({msg_count} messages)")

    assert result['total_participants'] == 3, "Expected 3 participants"
    print("\n✓ Test passed!")


def test_delayed_response():
    """Test with very long delay (should be filtered out)."""
    print("\nTest 5: Very long delay (>24 hours, should be filtered)")
    print("-" * 60)

    base_time = datetime(2026, 2, 11, 10, 0, 0)
    messages = [
        ("Alice", base_time),
        ("Bob", base_time + timedelta(hours=25)),  # 25 hours - should be filtered
        ("Alice", base_time + timedelta(hours=25, minutes=5)),  # 5 min response
    ]

    result = calculate_response_times(messages)

    print(f"Total messages: {result['total_messages']}")
    print("\nResponse times:")
    for rt in result['response_times']:
        sender = rt['sender']
        avg_mins = rt['avg_response_minutes']
        resp_count = rt['response_count']

        if avg_mins is not None:
            print(f"  {sender}: {avg_mins:.2f} minutes avg ({resp_count} responses)")
        else:
            print(f"  {sender}: No responses counted")

    # Bob's 25-hour response should be filtered out
    bob_stats = next(r for r in result['response_times'] if r['sender'] == 'Bob')
    assert bob_stats['response_count'] == 0, "Expected 0 responses (25h filtered)"

    # Alice's 5-min response should be counted
    alice_stats = next(r for r in result['response_times'] if r['sender'] == 'Alice')
    assert alice_stats['response_count'] == 1, "Expected 1 response (5 min)"
    assert alice_stats['avg_response_minutes'] == 5.0, "Expected 5.0 min average"

    print("\n✓ Test passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Response Times Calculation Unit Tests")
    print("=" * 60)

    test_basic_conversation()
    test_single_message()
    test_monologue()
    test_group_chat()
    test_delayed_response()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)

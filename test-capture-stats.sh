#!/bin/bash
# Test script for the /api/capture-stats endpoint
# Usage: ./test-capture-stats.sh [API_URL] [API_KEY]

API_URL="${1:-http://localhost:8900}"
API_KEY="${2:-changeme}"

echo "Testing capture-stats endpoint at ${API_URL}/api/capture-stats"
echo "Using API key: ${API_KEY}"
echo ""

# First, populate some test data via heartbeat endpoint
echo "Step 1: Populating test data via heartbeat endpoint..."
echo "-------------------------------------------------------"

# Test chat 1: Recent heartbeat, low errors (should be GREEN)
curl -s -X POST "${API_URL}/api/heartbeat" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"chatId\": \"green-chat\",
    \"messageCount\": 5,
    \"queueSize\": 0,
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%S)\"
  }" > /dev/null
echo "✓ Created green-chat (recent heartbeat, low errors)"

# Test chat 2: Old heartbeat, low errors (should be RED due to age)
curl -s -X POST "${API_URL}/api/heartbeat" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "chatId": "red-chat-old",
    "messageCount": 10,
    "queueSize": 0,
    "timestamp": "2026-02-11T13:00:00"
  }' > /dev/null
echo "✓ Created red-chat-old (old heartbeat)"

echo ""
echo "Step 2: Fetching capture stats..."
echo "-------------------------------------------------------"

# Now test the capture-stats endpoint
curl -s -X GET "${API_URL}/api/capture-stats" \
  -H "Authorization: Bearer ${API_KEY}" \
  | python3 -m json.tool

echo ""
echo "Tests completed!"
echo ""
echo "Expected results:"
echo "- green-chat: status='green' (recent heartbeat < 5min, errors < 10)"
echo "- red-chat-old: status='red' (heartbeat > 15min ago)"
echo "- Each entry should have: chat_id, last_heartbeat, messages_captured_24h, error_count_24h, status"

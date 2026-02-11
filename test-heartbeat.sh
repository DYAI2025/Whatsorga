#!/bin/bash
# Test script for the /api/heartbeat endpoint
# Usage: ./test-heartbeat.sh [API_URL] [API_KEY]

API_URL="${1:-http://localhost:8900}"
API_KEY="${2:-changeme}"

echo "Testing heartbeat endpoint at ${API_URL}/api/heartbeat"
echo "Using API key: ${API_KEY}"
echo ""

# Test 1: Send heartbeat for a test chat
echo "Test 1: Sending heartbeat for chat 'test-chat-001'"
curl -X POST "${API_URL}/api/heartbeat" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "chatId": "test-chat-001",
    "messageCount": 5,
    "queueSize": 0,
    "timestamp": "2026-02-11T14:00:00"
  }' \
  -w "\nHTTP Status: %{http_code}\n\n"

# Test 2: Send another heartbeat to test upsert logic
echo "Test 2: Sending second heartbeat for same chat (upsert test)"
curl -X POST "${API_URL}/api/heartbeat" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "chatId": "test-chat-001",
    "messageCount": 3,
    "queueSize": 1,
    "timestamp": "2026-02-11T14:01:00"
  }' \
  -w "\nHTTP Status: %{http_code}\n\n"

# Test 3: Send heartbeat for a different chat
echo "Test 3: Sending heartbeat for chat 'test-chat-002'"
curl -X POST "${API_URL}/api/heartbeat" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "chatId": "test-chat-002",
    "messageCount": 10,
    "queueSize": 2,
    "timestamp": "2026-02-11T14:02:00"
  }' \
  -w "\nHTTP Status: %{http_code}\n\n"

echo "Tests completed!"
echo ""
echo "Expected results:"
echo "- All responses should return: {\"status\":\"ok\"}"
echo "- HTTP Status should be: 200"
echo "- First heartbeat creates new CaptureStats entry"
echo "- Second heartbeat updates existing entry (messages_captured_24h should be 5+3=8)"

#!/bin/bash
# Test script for GET /api/communication-pattern/{chat_id}

set -e

API_KEY="${RADAR_API_KEY:-changeme-generate-a-random-token}"
BASE_URL="${API_BASE_URL:-http://localhost:8900}"
CHAT_ID="${1:-test_chat}"

echo "=========================================="
echo "Testing Communication Pattern Endpoint"
echo "=========================================="
echo "API URL: ${BASE_URL}"
echo "Chat ID: ${CHAT_ID}"
echo ""

# Test 1: Default parameters (30 days)
echo "Test 1: GET /api/communication-pattern/${CHAT_ID} (default 30 days)"
echo "------------------------------------------"
response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  "${BASE_URL}/api/communication-pattern/${CHAT_ID}" \
  -H "Authorization: Bearer ${API_KEY}")

http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)
body=$(echo "$response" | sed -e 's/HTTP_STATUS:.*$//')

if [ "$http_status" -eq 200 ]; then
    echo "✓ Status: 200 OK"
    echo "$body" | python3 -m json.tool
    echo ""
else
    echo "✗ FAILED: Expected 200, got ${http_status}"
    echo "$body"
    exit 1
fi

# Test 2: Custom days parameter (7 days)
echo "Test 2: GET /api/communication-pattern/${CHAT_ID}?days=7"
echo "------------------------------------------"
response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  "${BASE_URL}/api/communication-pattern/${CHAT_ID}?days=7" \
  -H "Authorization: Bearer ${API_KEY}")

http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)
body=$(echo "$response" | sed -e 's/HTTP_STATUS:.*$//')

if [ "$http_status" -eq 200 ]; then
    echo "✓ Status: 200 OK"
    echo "$body" | python3 -m json.tool
    echo ""
else
    echo "✗ FAILED: Expected 200, got ${http_status}"
    echo "$body"
    exit 1
fi

# Test 3: Test authentication (should fail without token)
echo "Test 3: Authentication check (no token - should fail)"
echo "------------------------------------------"
response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  "${BASE_URL}/api/communication-pattern/${CHAT_ID}")

http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)

if [ "$http_status" -eq 401 ] || [ "$http_status" -eq 403 ]; then
    echo "✓ Authentication required: Status ${http_status}"
else
    echo "✗ WARNING: Expected 401/403, got ${http_status}"
fi

echo ""
echo "=========================================="
echo "All tests completed!"
echo "=========================================="

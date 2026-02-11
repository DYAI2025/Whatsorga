#!/bin/bash
# Test script for monitoring.html implementation

echo "=== Monitoring Page Implementation Test ==="
echo ""

# Check if file exists
MONITORING_FILE="radar-api/app/dashboard/static/monitoring.html"
if [ ! -f "$MONITORING_FILE" ]; then
    echo "❌ FAIL: monitoring.html not found"
    exit 1
fi
echo "✓ monitoring.html exists"

# Check file size
FILE_SIZE=$(wc -c < "$MONITORING_FILE")
if [ "$FILE_SIZE" -lt 5000 ]; then
    echo "❌ FAIL: File too small (${FILE_SIZE} bytes)"
    exit 1
fi
echo "✓ File size: ${FILE_SIZE} bytes"

# Check for required features
echo ""
echo "Checking required features:"

# Chat cards
if grep -q "chat-card" "$MONITORING_FILE"; then
    echo "✓ Chat cards implemented"
else
    echo "❌ FAIL: Chat cards not found"
    exit 1
fi

# Status indicators (green/yellow/red)
if grep -q "status-indicator" "$MONITORING_FILE" && \
   grep -q "\.green" "$MONITORING_FILE" && \
   grep -q "\.yellow" "$MONITORING_FILE" && \
   grep -q "\.red" "$MONITORING_FILE"; then
    echo "✓ Status indicators (green/yellow/red) implemented"
else
    echo "❌ FAIL: Status indicators not complete"
    exit 1
fi

# Auto-refresh
if grep -q "REFRESH_INTERVAL" "$MONITORING_FILE" && \
   grep -q "30000" "$MONITORING_FILE"; then
    echo "✓ Auto-refresh (30s) implemented"
else
    echo "❌ FAIL: Auto-refresh not found"
    exit 1
fi

# API endpoint fetch
if grep -q "/api/capture-stats" "$MONITORING_FILE"; then
    echo "✓ Fetches from /api/capture-stats endpoint"
else
    echo "❌ FAIL: API endpoint not used"
    exit 1
fi

# Authentication
if grep -q "authenticate" "$MONITORING_FILE" && \
   grep -q "API_KEY" "$MONITORING_FILE"; then
    echo "✓ Authentication implemented"
else
    echo "❌ FAIL: Authentication not found"
    exit 1
fi

# Summary stats
if grep -q "summary" "$MONITORING_FILE" && \
   grep -q "totalChats" "$MONITORING_FILE"; then
    echo "✓ Summary statistics implemented"
else
    echo "❌ FAIL: Summary stats not found"
    exit 1
fi

# Heartbeat display
if grep -q "heartbeat" "$MONITORING_FILE" || \
   grep -q "last_heartbeat" "$MONITORING_FILE"; then
    echo "✓ Heartbeat display implemented"
else
    echo "❌ FAIL: Heartbeat display not found"
    exit 1
fi

# Messages and errors stats
if grep -q "messages_captured_24h" "$MONITORING_FILE" && \
   grep -q "error_count_24h" "$MONITORING_FILE"; then
    echo "✓ Message and error statistics displayed"
else
    echo "❌ FAIL: Stats not displayed"
    exit 1
fi

echo ""
echo "=== All Tests Passed ==="
echo ""
echo "To test manually:"
echo "1. Start the API server:"
echo "   cd radar-api && uvicorn app.main:app --host 0.0.0.0 --port 8900"
echo ""
echo "2. Open in browser:"
echo "   http://localhost:8900/dashboard/static/monitoring.html"
echo ""
echo "3. Enter your API key and verify:"
echo "   - Chat cards appear with colored status indicators"
echo "   - Summary shows total/green/yellow/red counts"
echo "   - Auto-refresh countdown works"
echo "   - Each card shows messages and errors (24h)"
echo "   - Last heartbeat time is displayed"

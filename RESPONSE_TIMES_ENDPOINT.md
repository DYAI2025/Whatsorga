# Response Times Endpoint - Implementation & Testing

## Overview

Implemented GET `/api/response-times/{chat_id}` endpoint that calculates average response times per sender based on message timestamps.

## Endpoint Details

**URL:** `GET /api/response-times/{chat_id}`

**Authentication:** Bearer token required

**Query Parameters:**
- `days` (optional): Number of days to analyze (default: 30, min: 1, max: 365)

**Response Format:**
```json
{
  "chat_id": "string",
  "days": 30,
  "response_times": [
    {
      "sender": "string",
      "avg_response_seconds": 300.0,
      "avg_response_minutes": 5.0,
      "response_count": 10,
      "message_count": 25
    }
  ],
  "total_messages": 50,
  "total_participants": 2
}
```

## Calculation Logic

The endpoint analyzes message timestamps to calculate how quickly each participant responds:

1. **Fetches messages** from the database for the specified chat within the time window
2. **Sorts messages** chronologically by timestamp
3. **Tracks sender changes** to identify actual responses (when sender differs from previous message)
4. **Calculates response time** as the time gap between consecutive messages from different senders
5. **Filters outliers** by excluding response times > 24 hours (likely conversation pauses, not responses)
6. **Averages per sender** to determine typical response speed
7. **Sorts results** by fastest average response time first

### Example Calculation

Given this conversation:
```
10:00 - Alice: "Hello"
10:05 - Bob: "Hi there!"        (Bob responds in 5 minutes)
10:10 - Alice: "How are you?"   (Alice responds in 5 minutes)
10:15 - Bob: "Great!"           (Bob responds in 5 minutes)
10:30 - Alice: "Nice"           (Alice responds in 15 minutes)
```

Results:
- **Bob**: 5.0 minutes average (2 responses: 5min + 5min)
- **Alice**: 10.0 minutes average (2 responses: 5min + 15min)

### Edge Cases Handled

1. **< 2 messages**: Returns error "Not enough messages to calculate response times"
2. **Same sender (monologue)**: Sender shows 0 responses, only message count
3. **Long delays (> 24 hours)**: Filtered out (not counted as responses)
4. **Group chats**: Tracks each participant independently

## Testing with curl

### Prerequisites

1. API must be running (either via Docker or locally)
2. Set environment variables:
   ```bash
   export RADAR_API_KEY="your-api-key"
   export API_BASE_URL="http://localhost:8900"  # or production URL
   ```

### Test Commands

#### 1. Basic Request (default 30 days)

```bash
curl -X GET "${API_BASE_URL}/api/response-times/test_chat" \
  -H "Authorization: Bearer ${RADAR_API_KEY}" \
  | python3 -m json.tool
```

**Expected Response (with data):**
```json
{
  "chat_id": "test_chat",
  "days": 30,
  "response_times": [
    {
      "sender": "Bob",
      "avg_response_seconds": 300.0,
      "avg_response_minutes": 5.0,
      "response_count": 15,
      "message_count": 42
    },
    {
      "sender": "Alice",
      "avg_response_seconds": 600.0,
      "avg_response_minutes": 10.0,
      "response_count": 12,
      "message_count": 38
    }
  ],
  "total_messages": 80,
  "total_participants": 2
}
```

**Expected Response (insufficient data):**
```json
{
  "chat_id": "test_chat",
  "days": 30,
  "response_times": [],
  "total_messages": 1,
  "error": "Not enough messages to calculate response times"
}
```

#### 2. Custom Time Window (7 days)

```bash
curl -X GET "${API_BASE_URL}/api/response-times/test_chat?days=7" \
  -H "Authorization: Bearer ${RADAR_API_KEY}" \
  | python3 -m json.tool
```

#### 3. Test Authentication (should fail)

```bash
# Without token - should return 401
curl -X GET "${API_BASE_URL}/api/response-times/test_chat"

# With invalid token - should return 403
curl -X GET "${API_BASE_URL}/api/response-times/test_chat" \
  -H "Authorization: Bearer invalid-token"
```

### Automated Test Scripts

Three test scripts are provided:

1. **`test-response-times.sh`** - Bash script with curl commands
   ```bash
   ./test-response-times.sh [chat_id]
   ```

2. **`test_curl_response_times.py`** - Python async script with httpx
   ```bash
   python3 test_curl_response_times.py
   ```

3. **`test_response_times_unit.py`** - Unit tests for calculation logic
   ```bash
   python3 test_response_times_unit.py
   ```

## Implementation Files

### Modified Files

1. **`radar-api/app/dashboard/router.py`**
   - Added `get_response_times()` endpoint function (lines 456-541)
   - Uses existing `Message` model and database session
   - Follows same auth pattern as other dashboard endpoints

### Test Files Created

1. **`test-response-times.sh`** - Shell script for curl testing
2. **`test_curl_response_times.py`** - Python async test with httpx
3. **`test_response_times_unit.py`** - Pure Python logic validation
4. **`test_response_times_mock.py`** - FastAPI mock endpoint test (requires dependencies)

## Unit Test Results

All unit tests pass successfully:

```
✓ Test 1: Basic back-and-forth conversation
  - Bob: 5.00 minutes avg (2 responses)
  - Alice: 10.00 minutes avg (2 responses)

✓ Test 2: Single message (error handling)
  - Returns error: "Not enough messages to calculate response times"

✓ Test 3: Monologue (same sender, no responses)
  - Alice: 0 responses, 3 messages

✓ Test 4: Group chat with 3 participants
  - Bob: 2.00 minutes avg
  - Charlie: 3.00 minutes avg
  - Alice: 5.00 minutes avg

✓ Test 5: Very long delay (>24 hours filtered)
  - 25-hour response correctly filtered out
  - 5-minute response correctly counted
```

## Integration with Dashboard

This endpoint can be used to power dashboard visualizations showing:

- **Response speed comparison** between participants
- **Communication engagement** (who responds more frequently)
- **Temporal analysis** (how response times change over different time windows)
- **Relationship health indicators** (faster responses = higher engagement)

### Suggested Visualizations

1. **Bar Chart**: Average response time per sender
2. **Table**: Sender stats with response count and message count
3. **Trend Line**: Response time changes over different time windows (7d, 30d, 90d)

## Performance Considerations

- Database query fetches only `sender` and `timestamp` columns (optimized)
- Query filtered by `chat_id` and time window (indexed)
- Calculation is in-memory O(n) where n = number of messages
- Results sorted by response time for easy display

## Future Enhancements

Potential improvements:
- Add median response time (in addition to average)
- Track response time percentiles (p50, p95, p99)
- Segment by time of day (work hours vs. evening)
- Track response time trends over time
- Include response time variance/stddev

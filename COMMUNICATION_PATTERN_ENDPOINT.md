# Communication Pattern Endpoint

## Overview

The `/api/communication-pattern/{chat_id}` endpoint provides a weekday x hour heatmap showing when conversations are most active. This enables pattern recognition for relationship dynamics and communication habits.

## Endpoint Details

**URL**: `GET /api/communication-pattern/{chat_id}`

**Authentication**: Required (Bearer token)

**Parameters**:
- `chat_id` (path parameter, required): The chat identifier to analyze
- `days` (query parameter, optional): Number of days to look back (default: 30, min: 1, max: 365)

## Response Format

```json
{
  "chat_id": "string",
  "days": 30,
  "heatmap": [
    [0, 0, 0, 0, 0, 5, 3, 2, 1, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  // Monday
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 2, 0, 0, 0, 0],  // Tuesday
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  // Wednesday
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  // Thursday
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 6, 0],  // Friday
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  // Saturday
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0]   // Sunday
  ],
  "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
  "hours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
  "total_messages": 20
}
```

### Field Descriptions

- **chat_id**: The chat identifier that was analyzed
- **days**: The number of days analyzed (echo of the query parameter)
- **heatmap**: A 7x24 matrix where:
  - Rows (0-6) represent weekdays (0=Monday, 6=Sunday)
  - Columns (0-23) represent hours of the day (0=midnight, 23=11PM)
  - Values are integer counts of messages sent during that weekday-hour combination
- **weekdays**: Labels for the 7 weekdays in order
- **hours**: Labels for the 24 hours in order
- **total_messages**: Sum of all messages in the heatmap

## Implementation Details

### Algorithm

1. Query all messages for the specified `chat_id` within the time window (`days` parameter)
2. Initialize a 7x24 matrix with zeros
3. For each message:
   - Extract weekday (0=Monday, 6=Sunday) using Python's `timestamp.weekday()`
   - Extract hour (0-23) using `timestamp.hour`
   - Increment the corresponding cell in the heatmap matrix
4. Return the complete heatmap with metadata

### Database Query

```python
select(Message.timestamp)
    .where(and_(Message.chat_id == chat_id, Message.timestamp >= since))
```

Only timestamps are retrieved to minimize data transfer. The aggregation happens in application code.

## Use Cases

1. **Relationship Pattern Recognition**: Identify when a couple typically communicates
2. **Conflict Detection**: Unusual late-night or early-morning patterns may indicate stress
3. **Engagement Tracking**: See if communication patterns are increasing or decreasing
4. **Timezone Awareness**: Detect shifts in communication times (e.g., during travel)

## Example Usage

### curl

```bash
# Default 30-day analysis
curl -X GET "http://localhost:8900/api/communication-pattern/my-chat-id" \
  -H "Authorization: Bearer YOUR_API_KEY"

# Last 7 days only
curl -X GET "http://localhost:8900/api/communication-pattern/my-chat-id?days=7" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Python

```python
import httpx

async def get_communication_pattern(chat_id: str, days: int = 30):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://localhost:8900/api/communication-pattern/{chat_id}",
            headers={"Authorization": "Bearer YOUR_API_KEY"},
            params={"days": days}
        )
        return response.json()

# Usage
pattern = await get_communication_pattern("my-chat-id", days=7)
print(f"Most active: {pattern['weekdays'][pattern['heatmap'].index(max(pattern['heatmap']))]}")
```

### JavaScript (Frontend)

```javascript
async function fetchCommunicationPattern(chatId, days = 30) {
  const response = await fetch(
    `/api/communication-pattern/${chatId}?days=${days}`,
    {
      headers: {
        'Authorization': 'Bearer ' + API_KEY
      }
    }
  );
  return await response.json();
}

// Render heatmap with a charting library
const data = await fetchCommunicationPattern('my-chat-id', 7);
renderHeatmap(data.heatmap, data.weekdays, data.hours);
```

## Frontend Visualization Ideas

1. **D3.js Heatmap**: Classic calendar-style heatmap with color intensity
2. **Chart.js Matrix**: Simple grid with color coding
3. **Plotly Heatmap**: Interactive hover tooltips showing exact counts
4. **Custom Canvas**: Draw a 7x24 grid with custom styling

Example with HTML/CSS:

```html
<div class="heatmap">
  <!-- For each weekday -->
  <div class="weekday-row">
    <span class="weekday-label">Monday</span>
    <!-- For each hour -->
    <div class="hour-cell" style="opacity: 0.5;">5</div>
    <div class="hour-cell" style="opacity: 0.3;">3</div>
    <!-- ... -->
  </div>
  <!-- ... -->
</div>
```

## Testing

### Test Script

A test script is provided at `test-communication-pattern.sh`:

```bash
./test-communication-pattern.sh [chat_id]
```

### Expected Test Results

1. HTTP 200 with valid authentication
2. HTTP 401/403 without authentication
3. Response contains all required fields
4. Heatmap is 7x24 matrix
5. Total messages equals sum of all heatmap cells

## Performance Considerations

- **Query Optimization**: Only timestamps are retrieved, not full message objects
- **Time Complexity**: O(n) where n is the number of messages in the time window
- **Memory**: 7x24 matrix (168 integers) plus message timestamps
- **Recommended Days Range**: 7-90 days for optimal balance of insight vs. performance

## Future Enhancements

1. **Aggregated Stats**: Add peak hours, peak days, average messages per day
2. **Trend Detection**: Compare current period vs. previous period
3. **Per-Sender Breakdown**: Split heatmap by sender to see individual patterns
4. **Timezone Handling**: Support user-specified timezones for display
5. **Custom Granularity**: Support hourly, daily, or weekly aggregations

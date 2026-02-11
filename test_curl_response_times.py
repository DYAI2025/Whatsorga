#!/usr/bin/env python3
"""Simple curl-style test for response times endpoint."""

import sys
import json

try:
    import httpx
except ImportError:
    print("Installing httpx...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "httpx"])
    import httpx

API_KEY = "changeme-generate-a-random-token"
BASE_URL = "http://localhost:8900"

async def test_endpoint():
    """Test the response times endpoint."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        print("Testing GET /api/response-times/{chat_id}")
        print("=" * 60)

        # Test 1: Check API health first
        try:
            print("\n1. Checking API health...")
            health = await client.get(f"{BASE_URL}/health")
            if health.status_code == 200:
                print(f"   ✓ API is running (status: {health.status_code})")
            else:
                print(f"   ✗ API health check failed (status: {health.status_code})")
                return
        except Exception as e:
            print(f"   ✗ Cannot connect to API: {e}")
            print("\n   Make sure the API is running:")
            print("   cd radar-api && uvicorn app.main:app --host 0.0.0.0 --port 8900")
            return

        # Test 2: Response times endpoint (should work even with no data)
        print("\n2. Testing /api/response-times/test_chat...")
        try:
            response = await client.get(
                f"{BASE_URL}/api/response-times/test_chat",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✓ Success!")
                print(f"\n   Response structure:")
                print(f"   - chat_id: {data.get('chat_id')}")
                print(f"   - days: {data.get('days')}")
                print(f"   - total_messages: {data.get('total_messages')}")
                print(f"   - total_participants: {data.get('total_participants')}")

                # Show response times if there's data
                response_times = data.get('response_times', [])
                if response_times:
                    print(f"\n   Response times by sender:")
                    for rt in response_times:
                        sender = rt.get('sender', 'Unknown')
                        avg_mins = rt.get('avg_response_minutes')
                        msg_count = rt.get('message_count', 0)
                        resp_count = rt.get('response_count', 0)

                        if avg_mins is not None:
                            print(f"   - {sender}: {avg_mins:.2f} minutes avg ({resp_count} responses, {msg_count} messages)")
                        else:
                            print(f"   - {sender}: No responses tracked ({msg_count} messages)")
                else:
                    print(f"\n   (No response time data available)")
                    if 'error' in data:
                        print(f"   Error: {data['error']}")

            elif response.status_code == 401 or response.status_code == 403:
                print(f"   ✗ Authentication failed")
                print(f"   Response: {response.text}")
            else:
                print(f"   ✗ Unexpected status code")
                print(f"   Response: {response.text}")

        except Exception as e:
            print(f"   ✗ Request failed: {e}")

        # Test 3: Test with days parameter
        print("\n3. Testing with days=7 parameter...")
        try:
            response = await client.get(
                f"{BASE_URL}/api/response-times/test_chat?days=7",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   ✓ Days parameter working: {data.get('days')}")
        except Exception as e:
            print(f"   ✗ Request failed: {e}")

        # Test 4: Test authentication (no token)
        print("\n4. Testing authentication (should fail without token)...")
        try:
            response = await client.get(
                f"{BASE_URL}/api/response-times/test_chat"
            )
            if response.status_code in [401, 403]:
                print(f"   ✓ Authentication required (status: {response.status_code})")
            else:
                print(f"   ✗ Expected 401/403, got {response.status_code}")
        except Exception as e:
            print(f"   ✗ Request failed: {e}")

        print("\n" + "=" * 60)
        print("Tests completed!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_endpoint())

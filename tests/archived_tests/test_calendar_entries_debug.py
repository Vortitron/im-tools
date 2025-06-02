#!/usr/bin/env python3
"""
Debug test specifically for calendar entries API to understand why it fails in HA.
"""

import asyncio
import sys
import json
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
from infomentor.auth import HUB_BASE_URL, DEFAULT_HEADERS
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')

async def debug_calendar_entries():
    """Debug calendar entries API specifically."""
    print("🔍 Debugging Calendar Entries API")
    print("=" * 60)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials in .env file")
        return
        
    print(f"👤 Testing with username: {username}")
    
    async with InfoMentorClient() as client:
        try:
            print("🔐 Authenticating...")
            if not await client.login(username, password):
                print("❌ Authentication failed")
                return
            
            print("✅ Authentication successful!")
            
            pupil_ids = await client.get_pupil_ids()
            print(f"📋 Found {len(pupil_ids)} pupils: {pupil_ids}")
            
            if not pupil_ids:
                print("❌ No pupils found")
                return
            
            pupil_id = pupil_ids[0]
            await client.switch_pupil(pupil_id)
            
            # Test for a specific date range
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=7)
            
            print(f"📅 Testing calendar entries for {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            print()
            
            # Make the exact same request as the client does
            calendar_entries_url = f"{HUB_BASE_URL}/calendarv2/calendarv2/getentries"
            headers = DEFAULT_HEADERS.copy()
            headers.update({
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/json; charset=UTF-8",
            })
            
            payload = {
                "startDate": start_date.strftime('%Y-%m-%d'),
                "endDate": end_date.strftime('%Y-%m-%d'),
            }
            
            print(f"🌐 Making request to: {calendar_entries_url}")
            print(f"📤 Headers: {json.dumps(headers, indent=2)}")
            print(f"📤 Payload: {json.dumps(payload, indent=2)}")
            print()
            
            # Use the same session as the client
            session = client._session
            
            print("🍪 Session cookies:")
            if hasattr(session, 'cookie_jar'):
                for cookie in session.cookie_jar:
                    print(f"  - {cookie.key}={cookie.value[:20]}... (domain: {cookie.get('domain', 'no-domain')})")
            else:
                print("  No cookies found")
            print()
            
            async with session.post(calendar_entries_url, headers=headers, json=payload) as resp:
                print(f"📥 Response status: {resp.status}")
                print(f"📥 Response headers:")
                for key, value in resp.headers.items():
                    print(f"  {key}: {value}")
                print()
                
                if resp.status == 200:
                    try:
                        # Get raw response text first
                        response_text = await resp.text()
                        print(f"📄 Raw response: '{response_text}'")
                        
                        # Try to parse as JSON
                        data = json.loads(response_text) if response_text else {}
                        print(f"✅ Success! Response type: {type(data)}")
                        print(f"📊 Response data: {data}")
                        
                        if isinstance(data, dict):
                            print(f"📋 Response keys: {list(data.keys())}")
                            
                            # Look for entries
                            entries = []
                            for key in ['entries', 'events', 'items', 'data', 'calendarEntries', 'calendar']:
                                if key in data and isinstance(data[key], list):
                                    entries = data[key]
                                    print(f"📋 Found {len(entries)} entries in '{key}'")
                                    break
                            
                            if entries:
                                print("📝 First few entries:")
                                for i, entry in enumerate(entries[:3]):
                                    print(f"  {i+1}. {entry.get('title', 'No title')} - {entry.get('startDate', 'No date')}")
                            else:
                                print("📭 No entries found in response")
                        else:
                            print(f"📊 Response is not a dict: {data}")
                    except Exception as e:
                        response_text = await resp.text()
                        print(f"❌ Failed to parse JSON: {e}")
                        print(f"📄 Raw response: '{response_text}'")
                else:
                    response_text = await resp.text()
                    print(f"❌ Request failed: HTTP {resp.status}")
                    print(f"📄 Response body: {response_text}")
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

async def test_with_fresh_session():
    """Test calendar entries with a fresh session to compare."""
    print("\n" + "=" * 60)
    print("🔄 Testing with fresh session (like HA might do)")
    print("=" * 60)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    # Create a fresh session like HA might
    async with aiohttp.ClientSession() as fresh_session:
        try:
            from infomentor.auth import InfoMentorAuth
            
            auth = InfoMentorAuth(fresh_session)
            print("🔐 Fresh authentication...")
            
            if not await auth.login(username, password):
                print("❌ Fresh authentication failed")
                return
            
            print("✅ Fresh authentication successful!")
            
            if not auth.pupil_ids:
                print("❌ No pupils found in fresh session")
                return
            
            pupil_id = auth.pupil_ids[0]
            await auth.switch_pupil(pupil_id)
            
            # Test calendar entries with fresh session
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=7)
            
            calendar_entries_url = f"{HUB_BASE_URL}/calendarv2/calendarv2/getentries"
            headers = DEFAULT_HEADERS.copy()
            headers.update({
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/json; charset=UTF-8",
            })
            
            payload = {
                "startDate": start_date.strftime('%Y-%m-%d'),
                "endDate": end_date.strftime('%Y-%m-%d'),
            }
            
            print(f"🌐 Fresh session request to: {calendar_entries_url}")
            
            async with fresh_session.post(calendar_entries_url, headers=headers, json=payload) as resp:
                print(f"📥 Fresh session response status: {resp.status}")
                
                if resp.status == 200:
                    response_text = await resp.text()
                    print(f"📄 Fresh session raw response: '{response_text}'")
                    data = json.loads(response_text) if response_text else {}
                    print(f"✅ Fresh session success! Response type: {type(data)}, data: {data}")
                else:
                    response_text = await resp.text()
                    print(f"❌ Fresh session failed: HTTP {resp.status}")
                    print(f"📄 Response body: {response_text}")
        
        except Exception as e:
            print(f"❌ Fresh session error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_calendar_entries())
    asyncio.run(test_with_fresh_session()) 
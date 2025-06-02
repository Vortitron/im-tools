#!/usr/bin/env python3
"""
Test to replicate exactly what Home Assistant does to compare with standalone behavior.
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

async def test_exactly_like_ha():
    """Test exactly like Home Assistant does."""
    print("🏠 Testing Exactly Like Home Assistant")
    print("=" * 60)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials in .env file")
        return
        
    print(f"👤 Testing with username: {username}")
    
    # Replicate coordinator behavior
    session = aiohttp.ClientSession()
    
    try:
        client = InfoMentorClient(session)
        
        # Enter async context like coordinator does
        await client.__aenter__()
        
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
        print(f"🎯 Testing with pupil: {pupil_id}")
        
        # Now test schedule retrieval like coordinator does
        print("\n📅 Testing schedule retrieval (like coordinator)...")
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(weeks=2)
        
        print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
        # This is what the coordinator calls
        schedule_days = await client.get_schedule(pupil_id, start_date, end_date)
        print(f"✅ Schedule retrieval successful! Got {len(schedule_days)} days")
        
        # Test individual components
        print("\n🧪 Testing individual components...")
        
        print("1. Testing timetable directly...")
        try:
            timetable_entries = await client.get_timetable(pupil_id, start_date, end_date)
            print(f"   ✅ Timetable: {len(timetable_entries)} entries")
        except Exception as e:
            print(f"   ❌ Timetable failed: {e}")
            
        print("2. Testing time registration directly...")
        try:
            time_registrations = await client.get_time_registration(pupil_id, start_date, end_date)
            print(f"   ✅ Time registration: {len(time_registrations)} entries")
        except Exception as e:
            print(f"   ❌ Time registration failed: {e}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await client.__aexit__(None, None, None)
        except:
            pass
        try:
            await session.close()
        except:
            pass

async def test_direct_calendar_request():
    """Test making the direct calendar request with current session state."""
    print("\n" + "=" * 60)
    print("📞 Testing Direct Calendar Request")
    print("=" * 60)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    session = aiohttp.ClientSession()
    
    try:
        client = InfoMentorClient(session)
        await client.__aenter__()
        
        if not await client.login(username, password):
            print("❌ Authentication failed")
            return
        
        pupil_ids = await client.get_pupil_ids()
        if not pupil_ids:
            print("❌ No pupils found")
            return
        
        await client.switch_pupil(pupil_ids[0])
        
        # Test the exact calendar request
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=7)
        
        calendar_entries_url = f"{HUB_BASE_URL}/calendarv2/calendarv2/getentries"
        
        # Test 1: GET request (our new approach)
        print("🔍 Test 1: GET request (new approach)")
        headers = DEFAULT_HEADERS.copy()
        headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        })
        
        params = {
            "startDate": start_date.strftime('%Y-%m-%d'),
            "endDate": end_date.strftime('%Y-%m-%d'),
        }
        
        async with session.get(calendar_entries_url, headers=headers, params=params) as resp:
            response_text = await resp.text()
            print(f"   Status: {resp.status}")
            if resp.status != 200:
                print(f"   Response: {response_text}")
                print(f"   Headers: {dict(resp.headers)}")
            else:
                print(f"   ✅ GET success")
        
        # Test 2: POST request (old approach)
        print("\n🔍 Test 2: POST request (old approach)")
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
        
        async with session.post(calendar_entries_url, headers=headers, json=payload) as resp:
            response_text = await resp.text()
            print(f"   Status: {resp.status}")
            if resp.status != 200:
                print(f"   Response: {response_text}")
                print(f"   Headers: {dict(resp.headers)}")
                
                # Check if this is the "Invalid Verb" error
                if "invalid verb" in response_text.lower() or "bad request" in response_text.lower():
                    print("   🚨 This is the 'Invalid Verb' error we've been seeing!")
            else:
                print(f"   ✅ POST success")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await client.__aexit__(None, None, None)
        except:
            pass
        try:
            await session.close()
        except:
            pass

if __name__ == "__main__":
    asyncio.run(test_exactly_like_ha())
    asyncio.run(test_direct_calendar_request()) 
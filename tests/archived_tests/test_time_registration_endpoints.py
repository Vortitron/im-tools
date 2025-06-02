#!/usr/bin/env python3
"""
Test specifically for time registration endpoints that might be causing Invalid Verb errors.
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

async def test_time_registration_endpoints():
    """Test time registration endpoints specifically."""
    print("⏰ Testing Time Registration Endpoints")
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
            print(f"🔄 Switched to pupil: {pupil_id}")
            
            # Test date range
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=7)
            
            # Test data
            date_params = {
                "startDate": start_date.strftime('%Y-%m-%d'),
                "endDate": end_date.strftime('%Y-%m-%d'),
            }
            
            print(f"📅 Testing date range: {date_params}")
            print()
            
            # Test 1: Time Registration GetTimeRegistrations endpoint
            print("🔍 Test 1: TimeRegistration/GetTimeRegistrations (POST)")
            try:
                time_reg_url = f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
                headers = DEFAULT_HEADERS.copy()
                headers.update({
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json; charset=UTF-8",
                })
                
                async with client._session.post(time_reg_url, headers=headers, json=date_params) as resp:
                    response_text = await resp.text()
                    print(f"   Status: {resp.status}")
                    
                    if resp.status == 400:
                        print(f"   🚨 HTTP 400 ERROR FOUND!")
                        print(f"   Response: {response_text}")
                        print(f"   Headers: {dict(resp.headers)}")
                        
                        if "invalid verb" in response_text.lower():
                            print("   🎯 This is the 'Invalid Verb' error source!")
                    elif resp.status == 200:
                        try:
                            data = json.loads(response_text) if response_text else {}
                            print(f"   ✅ Success! Data type: {type(data)}")
                        except:
                            print(f"   ✅ Success! Raw response")
                    else:
                        print(f"   ⚠️ HTTP {resp.status}: {response_text[:100]}...")
                        
            except Exception as e:
                print(f"   ❌ Exception: {e}")
            
            print()
            
            # Test 2: Time Registration GetCalendarData endpoint
            print("🔍 Test 2: TimeRegistration/GetCalendarData (POST)")
            try:
                time_cal_url = f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetCalendarData/"
                headers = DEFAULT_HEADERS.copy()
                headers.update({
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json; charset=UTF-8",
                })
                
                async with client._session.post(time_cal_url, headers=headers, json=date_params) as resp:
                    response_text = await resp.text()
                    print(f"   Status: {resp.status}")
                    
                    if resp.status == 400:
                        print(f"   🚨 HTTP 400 ERROR FOUND!")
                        print(f"   Response: {response_text}")
                        print(f"   Headers: {dict(resp.headers)}")
                        
                        if "invalid verb" in response_text.lower():
                            print("   🎯 This is the 'Invalid Verb' error source!")
                    elif resp.status == 200:
                        try:
                            data = json.loads(response_text) if response_text else {}
                            print(f"   ✅ Success! Data type: {type(data)}")
                        except:
                            print(f"   ✅ Success! Raw response")
                    else:
                        print(f"   ⚠️ HTTP {resp.status}: {response_text[:100]}...")
                        
            except Exception as e:
                print(f"   ❌ Exception: {e}")
            
            print()
            
            # Test 3: Try GET requests for these endpoints
            print("🔍 Test 3: Same endpoints with GET method")
            
            for name, url in [
                ("GetTimeRegistrations", f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetTimeRegistrations/"),
                ("GetCalendarData", f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetCalendarData/")
            ]:
                print(f"   Testing {name} with GET...")
                try:
                    headers = DEFAULT_HEADERS.copy()
                    headers.update({
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                    })
                    
                    async with client._session.get(url, headers=headers, params=date_params) as resp:
                        response_text = await resp.text()
                        print(f"      Status: {resp.status}")
                        if resp.status == 200:
                            print(f"      ✅ GET works for {name}!")
                        else:
                            print(f"      ❌ GET failed: {response_text[:50]}...")
                except Exception as e:
                    print(f"      ❌ Exception: {e}")
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_time_registration_endpoints()) 
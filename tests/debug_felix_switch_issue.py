#!/usr/bin/env python3
"""
Debug script for Felix's specific switching and timetable access issues.
"""

import asyncio
import sys
import os
import re
from pathlib import Path
from datetime import datetime, timedelta

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')

async def debug_felix_switch_issue():
    """Debug Felix's switching and timetable access issues."""
    print("🔍 Felix Switch & Timetable Issue Debug")
    print("=" * 50)
    
    username = os.getenv('INFOMENTOR_USERNAME')
    password = os.getenv('INFOMENTOR_PASSWORD')
    
    if not username or not password:
        print("❌ Missing credentials in .env file")
        return
    
    async with InfoMentorClient() as client:
        print("\n🔐 Step 1: Authentication")
        print("-" * 30)
        
        try:
            await client.login(username, password)
            print("✅ Authentication successful")
        except Exception as e:
            print(f"❌ Authentication failed: {e}")
            return
        
        # Get pupil information
        pupil_ids = await client.get_pupil_ids()
        print(f"👥 Found {len(pupil_ids)} pupils: {pupil_ids}")
        
        # Check switch ID mapping
        print(f"🔗 Switch ID mapping: {client.auth.pupil_switch_ids}")
        
        # Find Felix
        felix_id = "1806227557"  # From the user's data
        if felix_id not in pupil_ids:
            print(f"❌ Felix ID {felix_id} not found in pupil list")
            return
        
        felix_switch_id = client.auth.pupil_switch_ids.get(felix_id, felix_id)
        print(f"🧒 Felix: ID={felix_id}, Switch ID={felix_switch_id}")
        
        print("\n🔄 Step 2: Testing Switch Methods")
        print("-" * 30)
        
        # Test switch with detailed error capturing
        try:
            print("🔧 Attempting hub switch...")
            hub_switch_url = f"https://hub.infomentor.se/Account/PupilSwitcher/SwitchPupil/{felix_switch_id}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Referer': 'https://hub.infomentor.se/#/',
                'Upgrade-Insecure-Requests': '1',
            }
            
            async with client._session.get(hub_switch_url, headers=headers, allow_redirects=False) as resp:
                print(f"   Response: {resp.status}")
                print(f"   Headers: {dict(resp.headers)}")
                
                if resp.status == 302:
                    location = resp.headers.get('Location', 'No location header')
                    print(f"   Redirect to: {location}")
                    
                    # Follow the redirect
                    if location and not location.startswith('http'):
                        location = f"https://hub.infomentor.se{location}"
                    
                    if location.startswith('http'):
                        async with client._session.get(location, headers=headers) as final_resp:
                            print(f"   Final response: {final_resp.status}")
                            if final_resp.status == 200:
                                print("   ✅ Switch appears successful")
                            else:
                                final_text = await final_resp.text()
                                print(f"   ❌ Final response failed: {final_text[:200]}...")
                elif resp.status == 400:
                    response_text = await resp.text()
                    print(f"   ❌ HTTP 400 Error: {response_text[:200]}...")
                else:
                    response_text = await resp.text()
                    print(f"   Response body: {response_text[:200]}...")
            
        except Exception as e:
            print(f"   ❌ Switch error: {e}")
        
        print("\n🗓️ Step 3: Testing Timetable Access")
        print("-" * 30)
        
        # Test direct timetable API call
        try:
            # Use a specific date range from the user's data
            start_date = datetime(2025, 6, 3)  # Tuesday from user's data
            end_date = datetime(2025, 6, 5)    # Thursday from user's data
            
            timetable_url = "https://hub.infomentor.se/timetable/timetable/gettimetablelist"
            headers = {
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            
            params = {
                'startDate': start_date.strftime('%Y-%m-%d'),
                'endDate': end_date.strftime('%Y-%m-%d'),
            }
            
            print(f"📅 Testing timetable for {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            print(f"🌐 URL: {timetable_url}")
            print(f"📋 Params: {params}")
            
            async with client._session.get(timetable_url, headers=headers, params=params) as resp:
                print(f"   Response: {resp.status}")
                
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   ✅ Success! Data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                    print(f"   Data type: {type(data)}")
                    if isinstance(data, dict):
                        for key, value in data.items():
                            print(f"     {key}: {type(value)} - {len(str(value))} chars")
                elif resp.status == 500:
                    response_text = await resp.text()
                    print(f"   ❌ HTTP 500 Error: {response_text}")
                    if "HandleUnauthorizedRequest" in response_text:
                        print("   🔍 This indicates session/pupil context issue")
                elif resp.status == 400:
                    response_text = await resp.text()
                    print(f"   ❌ HTTP 400 Error: {response_text}")
                else:
                    response_text = await resp.text()
                    print(f"   ❌ HTTP {resp.status}: {response_text[:200]}...")
                    
        except Exception as e:
            print(f"   ❌ Timetable test error: {e}")
        
        print("\n🔧 Step 4: Alternative Data Sources")
        print("-" * 30)
        
        # Test calendar endpoint as alternative
        try:
            calendar_url = "https://hub.infomentor.se/calendarv2/calendarv2/getentries"
            
            async with client._session.get(calendar_url, headers=headers, params=params) as resp:
                print(f"📅 Calendar endpoint: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   ✅ Calendar data available: {len(str(data))} chars")
                    # Look for timetable-like entries
                    if isinstance(data, dict) and 'entries' in data:
                        entries = data['entries']
                        print(f"   📋 Found {len(entries)} calendar entries")
                        
                        # Sample a few entries
                        for i, entry in enumerate(entries[:3]):
                            print(f"     Entry {i+1}: {entry.get('title', 'No title')[:50]}...")
                else:
                    print(f"   ❌ Calendar failed: {resp.status}")
                    
        except Exception as e:
            print(f"   ❌ Calendar test error: {e}")
        
        print("\n📊 Step 5: Session State Analysis")
        print("-" * 30)
        
        # Check session cookies
        print(f"🍪 Session cookies: {len(client._session.cookie_jar)}")
        
        # Check if we can access hub home
        try:
            hub_home = "https://hub.infomentor.se/#/"
            async with client._session.get(hub_home) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    print(f"🏠 Hub home accessible: {resp.status}")
                    
                    # Check for authentication indicators
                    auth_indicators = [
                        'logout' in html.lower(),
                        'switchpupil' in html.lower(),
                        felix_id in html,
                        felix_switch_id in html,
                    ]
                    print(f"   Auth indicators: {auth_indicators}")
                    
                    # Look for current pupil context
                    if 'current' in html.lower() and 'pupil' in html.lower():
                        print("   💡 Found current pupil context in page")
                else:
                    print(f"🏠 Hub home failed: {resp.status}")
        except Exception as e:
            print(f"   ❌ Hub home test error: {e}")
        
        print("\n🎯 Summary & Recommendations")
        print("-" * 30)
        
        print("Based on the test results:")
        print("1. If switch returns HTTP 400: Switch ID mapping issue")
        print("2. If timetable returns HTTP 500 with HandleUnauthorizedRequest: Session context issue")
        print("3. If calendar works but timetable doesn't: Endpoint-specific authorization")
        print("4. Check if Felix has timetable access permissions in InfoMentor")

if __name__ == "__main__":
    asyncio.run(debug_felix_switch_issue()) 
#!/usr/bin/env python3

import asyncio
import os
import sys
sys.path.append('/var/www/im-tools/custom_components/infomentor/infomentor')

from datetime import datetime, timedelta

async def debug_switching_detailed():
    """Debug pupil switching with detailed logging."""
    
    # Import after adding to path
    from auth import InfoMentorAuth
    from client import InfoMentorClient
    import aiohttp
    
    username = os.getenv('IM_USERNAME')
    password = os.getenv('IM_PASSWORD')
    
    if not username or not password:
        print('❌ Missing credentials')
        return
    
    print("🔍 DETAILED PUPIL SWITCHING DEBUG")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        auth = InfoMentorAuth(session)
        
        print("🔐 Step 1: Authenticating...")
        if not await auth.login(username, password):
            print('❌ Login failed')
            return
        
        print(f"✅ Authentication successful!")
        print(f"📋 Pupil IDs: {auth.pupil_ids}")
        print(f"🔗 Switch ID mapping: {auth.pupil_switch_ids}")
        
        # Test switching to each pupil explicitly
        for i, pupil_id in enumerate(auth.pupil_ids):
            switch_id = auth.pupil_switch_ids.get(pupil_id, 'NOT_FOUND')
            print(f"\n👤 Testing Pupil {i+1}: {pupil_id}")
            print(f"   Switch ID: {switch_id}")
            print("-" * 50)
            
            if switch_id == 'NOT_FOUND':
                print("   ❌ No switch ID found for this pupil!")
                continue
            
            # Test the switch
            print(f"🔄 Switching to pupil {pupil_id} (switch ID: {switch_id})...")
            switch_result = await auth.switch_pupil(pupil_id)
            print(f"   Switch result: {'✅ SUCCESS' if switch_result else '❌ FAILED'}")
            
            if not switch_result:
                continue
                
            # Now make a direct API call to check the session state
            print("📊 Testing API call with current session...")
            
            try:
                from constants import HUB_BASE_URL, DEFAULT_HEADERS
                
                week_start = datetime(2025, 5, 26)
                week_end = datetime(2025, 6, 1)
                
                # Test time registration API call
                time_reg_url = f"{HUB_BASE_URL}/TimeRegistration/TimeRegistration/GetTimeRegistrations/"
                headers = DEFAULT_HEADERS.copy()
                headers.update({
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                })
                
                params = {
                    "startDate": week_start.strftime('%Y-%m-%d'),
                    "endDate": week_end.strftime('%Y-%m-%d'),
                }
                
                print(f"   Making API call to: {time_reg_url}")
                print(f"   Params: {params}")
                
                async with session.get(time_reg_url, headers=headers, params=params) as resp:
                    print(f"   Response status: {resp.status}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        days = data.get('days', [])
                        print(f"   Found {len(days)} time registration days")
                        
                        # Show first few entries
                        for j, day in enumerate(days[:3]):
                            date = day.get('date', 'No date')
                            start_time = day.get('startDateTime', 'No start')
                            end_time = day.get('endDateTime', 'No end')
                            print(f"     {j+1}. {date}: {start_time} to {end_time}")
                            
                    else:
                        response_text = await resp.text()
                        print(f"   ❌ API call failed: {response_text[:100]}...")
                        
            except Exception as e:
                print(f"   ❌ API call exception: {e}")
        
        print(f"\n🎯 CONCLUSION:")
        if len(set(auth.pupil_switch_ids.values())) == len(auth.pupil_ids):
            print("✅ Each pupil has a unique switch ID - mapping looks correct")
        else:
            print("❌ Switch ID mapping has duplicates or missing values")

if __name__ == "__main__":
    asyncio.run(debug_switching_detailed()) 
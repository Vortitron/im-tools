#!/usr/bin/env python3
"""
Debug script to investigate pupil switching issue.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import re

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')

async def debug_pupil_switching():
    """Debug pupil switching and find correct switch IDs."""
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials")
        return
    
    async with InfoMentorClient() as client:
        print(f"🔐 Authenticating...")
        if not await client.login(username, password):
            print("❌ Authentication failed")
            return
        
        pupil_ids = await client.get_pupil_ids()
        print(f"📋 Found pupils: {pupil_ids}")
        
        # Try to get the main page HTML to find switch URLs
        print("\n🔍 Looking for switch URLs...")
        try:
            # Access the hub page to find pupil switch URLs
            headers = {'User-Agent': 'Mozilla/5.0'}
            hub_url = "https://hub.infomentor.se/#/"
            
            async with client.auth.session.get(hub_url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    
                    # Look for switch URLs with pupil names
                    switch_pattern = r'/Account/PupilSwitcher/SwitchPupil/(\d+)[^>]*>([^<]+)</a>'
                    matches = re.findall(switch_pattern, html)
                    
                    if matches:
                        print("✅ Found switch URLs:")
                        for switch_id, name in matches:
                            print(f"   - {name.strip()}: SwitchPupil/{switch_id}")
                    else:
                        # Try another pattern
                        switch_pattern2 = r'"switchPupilUrl"\s*:\s*"[^"]*SwitchPupil/(\d+)"[^}]*"name"\s*:\s*"([^"]+)"'
                        matches2 = re.findall(switch_pattern2, html)
                        
                        if matches2:
                            print("✅ Found switch URLs (from JSON):")
                            for switch_id, name in matches2:
                                print(f"   - {name}: SwitchPupil/{switch_id}")
                        else:
                            print("⚠️  No switch URLs found in HTML")
                            
                            # Save HTML for manual inspection
                            with open('debug_hub_page.html', 'w', encoding='utf-8') as f:
                                f.write(html)
                            print("   Saved HTML to debug_hub_page.html for inspection")
        except Exception as e:
            print(f"❌ Error getting hub page: {e}")
        
        # Test time registration for each pupil WITHOUT switching
        print("\n📊 Testing time registration WITHOUT explicit switching:")
        
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        days_since_monday = start_date.weekday()
        week_start = start_date - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        
        for i, pupil_id in enumerate(pupil_ids):
            print(f"\n👤 Pupil {i+1}: {pupil_id}")
            
            # Get time registration WITHOUT switching
            try:
                time_reg = await client.get_time_registration(pupil_id, week_start, week_end)
                print(f"   Found {len(time_reg)} time registration entries")
                
                if time_reg:
                    for j, entry in enumerate(time_reg[:2]):
                        date_str = entry.date.strftime('%Y-%m-%d %A')
                        times = f"{entry.start_time.strftime('%H:%M') if entry.start_time else '?'}-{entry.end_time.strftime('%H:%M') if entry.end_time else '?'}"
                        print(f"     {j+1}. {date_str}: {times} ({entry.type})")
            except Exception as e:
                print(f"   ❌ Error: {e}")
        
        # Now test WITH switching
        print("\n📊 Testing time registration WITH explicit switching:")
        
        for i, pupil_id in enumerate(pupil_ids):
            print(f"\n👤 Pupil {i+1}: {pupil_id}")
            
            # Try to switch
            print(f"   Attempting to switch to pupil {pupil_id}...")
            switch_result = await client.switch_pupil(pupil_id)
            print(f"   Switch result: {switch_result}")
            
            # Get time registration AFTER switching
            try:
                time_reg = await client.get_time_registration(pupil_id, week_start, week_end)
                print(f"   Found {len(time_reg)} time registration entries")
                
                if time_reg:
                    for j, entry in enumerate(time_reg[:2]):
                        date_str = entry.date.strftime('%Y-%m-%d %A')
                        times = f"{entry.start_time.strftime('%H:%M') if entry.start_time else '?'}-{entry.end_time.strftime('%H:%M') if entry.end_time else '?'}"
                        print(f"     {j+1}. {date_str}: {times} ({entry.type})")
            except Exception as e:
                print(f"   ❌ Error: {e}")
        
        # Try to identify pupils by their schedules
        print("\n🔍 Identifying pupils by their schedules:")
        print("   Felix (school pupil) should have fritids 12-16/17 + Thursday")
        print("   Isolde should have 8-16 Mon-Thu")

if __name__ == "__main__":
    asyncio.run(debug_pupil_switching()) 
#!/usr/bin/env python3
"""
Quick debug script to investigate timetable/calendar entry issues.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')

async def debug_timetable():
    """Debug timetable/calendar entries."""
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
        
        if not pupil_ids:
            return
        
        pupil_id = pupil_ids[0]
        print(f"👤 Testing with pupil: {pupil_id}")
        
        # Test current week
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=7)
        
        print(f"📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
        # Test time registration (should work)
        print("\n🕐 Testing Time Registration:")
        try:
            time_reg = await client.get_time_registration(pupil_id, start_date, end_date)
            print(f"   Found {len(time_reg)} entries")
            for i, entry in enumerate(time_reg[:3]):
                print(f"   {i+1}. {entry.date.strftime('%Y-%m-%d')} {entry.type}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test timetable (the problematic one)
        print("\n📚 Testing Timetable:")
        try:
            timetable = await client.get_timetable(pupil_id, start_date, end_date)
            print(f"   Found {len(timetable)} entries")
            for i, entry in enumerate(timetable[:3]):
                print(f"   {i+1}. {entry.date.strftime('%Y-%m-%d')} {entry.subject or 'No subject'}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test different date ranges
        print("\n📅 Testing Different Date Ranges:")
        
        # Last week
        last_week_start = start_date - timedelta(days=7)
        last_week_end = start_date
        print(f"   Last week: {last_week_start.strftime('%Y-%m-%d')} to {last_week_end.strftime('%Y-%m-%d')}")
        try:
            timetable = await client.get_timetable(pupil_id, last_week_start, last_week_end)
            print(f"   Found {len(timetable)} timetable entries")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Next week
        next_week_start = start_date + timedelta(days=7)
        next_week_end = next_week_start + timedelta(days=7)
        print(f"   Next week: {next_week_start.strftime('%Y-%m-%d')} to {next_week_end.strftime('%Y-%m-%d')}")
        try:
            timetable = await client.get_timetable(pupil_id, next_week_start, next_week_end)
            print(f"   Found {len(timetable)} timetable entries")
        except Exception as e:
            print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(debug_timetable()) 
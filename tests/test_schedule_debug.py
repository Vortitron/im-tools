#!/usr/bin/env python3
"""
Debug test to check why schedule data isn't being retrieved properly.
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.resolve() / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')

async def debug_schedule_retrieval():
    """Debug schedule retrieval to understand why no data is returned."""
    print("🔍 Debugging Schedule Retrieval")
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
            
            # Test for week 22 (2-6 June 2025) as shown in screenshots
            monday_june_2 = datetime(2025, 6, 2)
            friday_june_6 = datetime(2025, 6, 6)
            
            print(f"📅 Testing for week 22: {monday_june_2.strftime('%Y-%m-%d')} to {friday_june_6.strftime('%Y-%m-%d')}")
            print()
            
            for pupil_id in pupil_ids:
                pupil_info = await client.get_pupil_info(pupil_id)
                pupil_name = pupil_info.name if pupil_info else f"Pupil {pupil_id}"
                
                print(f"👤 Debugging {pupil_name} (ID: {pupil_id})")
                print("-" * 50)
                
                # Switch to this pupil first
                await client.switch_pupil(pupil_id)
                
                # Test 1: Direct timetable API call
                print("📚 Testing timetable API...")
                try:
                    timetable_entries = await client.get_timetable(pupil_id, monday_june_2, friday_june_6)
                    print(f"   Found {len(timetable_entries)} timetable entries")
                    for entry in timetable_entries[:3]:  # Show first 3
                        subject = entry.subject or entry.title or "Unknown"
                        time_str = ""
                        if entry.start_time and entry.end_time:
                            time_str = f" ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})"
                        print(f"     - {entry.date.strftime('%Y-%m-%d')}: {subject}{time_str}")
                except Exception as e:
                    print(f"   ❌ Timetable error: {e}")
                
                # Test 2: Direct time registration API call
                print("⏰ Testing time registration API...")
                try:
                    time_registrations = await client.get_time_registration(pupil_id, monday_june_2, friday_june_6)
                    print(f"   Found {len(time_registrations)} time registrations")
                    for reg in time_registrations[:3]:  # Show first 3
                        time_str = ""
                        if reg.start_time and reg.end_time:
                            time_str = f" ({reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')})"
                        status = f" [{reg.status}]" if reg.status else ""
                        print(f"     - {reg.date.strftime('%Y-%m-%d')}: Registration{time_str}{status}")
                except Exception as e:
                    print(f"   ❌ Time registration error: {e}")
                
                # Test 3: Combined schedule API call
                print("📅 Testing combined schedule API...")
                try:
                    schedule_days = await client.get_schedule(pupil_id, monday_june_2, friday_june_6)
                    print(f"   Found {len(schedule_days)} schedule days")
                    for day in schedule_days[:3]:  # Show first 3
                        print(f"     - {day.date.strftime('%Y-%m-%d')}: School={day.has_school}, Preschool/Fritids={day.has_preschool_or_fritids}")
                        print(f"       Timetable entries: {len(day.timetable_entries)}, Time registrations: {len(day.time_registrations)}")
                except Exception as e:
                    print(f"   ❌ Schedule error: {e}")
                
                print()
                
                # Test 4: Try a different date range - current week
                print("📅 Testing current week...")
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                week_start = today - timedelta(days=today.weekday())  # Start of this week
                week_end = week_start + timedelta(days=6)
                
                try:
                    schedule_days = await client.get_schedule(pupil_id, week_start, week_end)
                    print(f"   Current week ({week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}): {len(schedule_days)} days")
                    for day in schedule_days:
                        if day.has_school or day.has_preschool_or_fritids:
                            print(f"     - {day.date.strftime('%Y-%m-%d')}: School={day.has_school}, Preschool/Fritids={day.has_preschool_or_fritids}")
                except Exception as e:
                    print(f"   ❌ Current week error: {e}")
                
                print("=" * 50)
                print()
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_schedule_retrieval()) 
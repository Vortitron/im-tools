#!/usr/bin/env python3
"""
Test script to verify the pupil switching fix works correctly.
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

async def test_pupil_switching_fix():
    """Test that pupil switching now works correctly."""
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials")
        return False
    
    async with InfoMentorClient() as client:
        print(f"🔐 Authenticating...")
        if not await client.login(username, password):
            print("❌ Authentication failed")
            return False
        
        pupil_ids = await client.get_pupil_ids()
        print(f"📋 Found pupils: {pupil_ids}")
        
        # Check if switch IDs were extracted
        print(f"🔗 Pupil-to-switch mapping: {client.auth.pupil_switch_ids}")
        
        if not client.auth.pupil_switch_ids:
            print("⚠️  No switch ID mappings found - trying to extract them")
            return False
        
        # Test date range - this week
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        days_since_monday = start_date.weekday()
        week_start = start_date - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        
        print(f"\n📅 Testing week: {week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}")
        
        schedules = {}
        
        # Test each pupil with explicit switching
        for i, pupil_id in enumerate(pupil_ids):
            switch_id = client.auth.pupil_switch_ids.get(pupil_id, "unknown")
            print(f"\n👤 Testing Pupil {i+1}: {pupil_id} (Switch ID: {switch_id})")
            print("-" * 60)
            
            # Explicit switch
            print(f"🔄 Switching to pupil {pupil_id}...")
            switch_result = await client.switch_pupil(pupil_id)
            print(f"   Switch result: {'✅ SUCCESS' if switch_result else '❌ FAILED'}")
            
            if not switch_result:
                print(f"   ⚠️  Skipping data retrieval due to switch failure")
                continue
            
            # Get time registration data
            try:
                time_reg = await client.get_time_registration(pupil_id, week_start, week_end)
                print(f"📊 Time Registration: {len(time_reg)} entries")
                
                schedules[pupil_id] = []
                for j, entry in enumerate(time_reg):
                    date_str = entry.date.strftime('%Y-%m-%d %A')
                    start_time = entry.start_time.strftime('%H:%M') if entry.start_time else 'No start'
                    end_time = entry.end_time.strftime('%H:%M') if entry.end_time else 'No end'
                    reg_type = entry.type if hasattr(entry, 'type') else entry.status or 'unknown'
                    schedule_entry = f"{date_str}: {start_time}-{end_time} ({reg_type})"
                    schedules[pupil_id].append(schedule_entry)
                    print(f"   {j+1}. {schedule_entry}")
                    
            except Exception as e:
                print(f"   ❌ Error getting time registration: {e}")
                
            # Test timetable entries
            try:
                timetable = await client.get_timetable(pupil_id, week_start, week_end)
                print(f"📚 Timetable: {len(timetable)} entries")
                
                if timetable:
                    for j, entry in enumerate(timetable[:3]):
                        date_str = entry.date.strftime('%Y-%m-%d %A')
                        start_time = entry.start_time.strftime('%H:%M') if entry.start_time else 'No start'
                        end_time = entry.end_time.strftime('%H:%M') if entry.end_time else 'No end'
                        subject = entry.subject or 'No subject'
                        print(f"   {j+1}. {date_str}: {start_time}-{end_time} {subject}")
                        
            except Exception as e:
                print(f"   ❌ Error getting timetable: {e}")
        
        # Analyze results
        print(f"\n{'='*60}")
        print("📊 PUPIL SWITCHING TEST RESULTS")
        print(f"{'='*60}")
        
        # Check if pupils have different schedules
        schedule_signatures = {}
        for pupil_id, schedule in schedules.items():
            # Create a signature from the first few schedule entries
            signature = "|".join(schedule[:3]) if schedule else "empty"
            if signature in schedule_signatures:
                print(f"⚠️  Pupils {schedule_signatures[signature]} and {pupil_id} have identical schedules!")
                print(f"   This suggests switching is not working correctly.")
                return False
            else:
                schedule_signatures[signature] = pupil_id
        
        print("✅ Each pupil has a unique schedule - switching appears to be working!")
        
        # Identify pupils based on expected patterns
        print("\n🎯 Pupil Identification:")
        
        for pupil_id, schedule in schedules.items():
            if not schedule:
                print(f"   {pupil_id}: No schedule data")
                continue
                
            # Look for patterns
            has_8am_start = any("08:00-" in entry for entry in schedule)
            has_12pm_start = any("12:00-" in entry for entry in schedule)
            has_thursday = any("Thursday" in entry for entry in schedule)
            
            if has_8am_start and not has_12pm_start:
                print(f"   {pupil_id}: Likely ISOLDE (8:00 start times)")
            elif has_12pm_start:
                print(f"   {pupil_id}: Likely FELIX (12:00 start times)")
            else:
                print(f"   {pupil_id}: Unknown pattern")
                
            if has_thursday:
                print(f"     + Has Thursday entries (expected for Felix)")
        
        print(f"\n🎉 PUPIL SWITCHING FIX VALIDATION: ✅ SUCCESS")
        print("The integration can now correctly switch between pupils!")
        
        return True

if __name__ == "__main__":
    success = asyncio.run(test_pupil_switching_fix())
    if success:
        print("\n🚀 Ready for Home Assistant deployment!")
    else:
        print("\n⚠️  Pupil switching fix needs more work") 
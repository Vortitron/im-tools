#!/usr/bin/env python3
"""
Detailed test to verify pupil switching by checking multiple data sources.
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

async def test_detailed_pupil_switching():
    """Test pupil switching with multiple data sources."""
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
        print(f"🔗 Switch mapping: {client.auth.pupil_switch_ids}")
        
        if len(pupil_ids) < 2:
            print("❌ Need at least 2 pupils to test switching")
            return False
        
        # Test with multiple date ranges to find differences
        date_ranges = []
        
        # Current week
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        days_since_monday = start_date.weekday()
        week_start = start_date - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        date_ranges.append(("This week", week_start, week_end))
        
        # Last week
        last_week_start = week_start - timedelta(days=7)
        last_week_end = week_start - timedelta(days=1)
        date_ranges.append(("Last week", last_week_start, last_week_end))
        
        # Current month
        month_start = start_date.replace(day=1)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1) - timedelta(days=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1) - timedelta(days=1)
        date_ranges.append(("This month", month_start, month_end))
        
        pupil_data = {}
        
        for pupil_id in pupil_ids:
            switch_id = client.auth.pupil_switch_ids.get(pupil_id, "unknown")
            print(f"\n👤 Testing Pupil: {pupil_id} (Switch ID: {switch_id})")
            print("=" * 60)
            
            # Switch to this pupil
            print(f"🔄 Switching to pupil {pupil_id}...")
            switch_result = await client.switch_pupil(pupil_id)
            print(f"   Switch result: {'✅ SUCCESS' if switch_result else '❌ FAILED'}")
            
            if not switch_result:
                continue
            
            pupil_data[pupil_id] = {
                'switch_id': switch_id,
                'time_registrations': {},
                'timetables': {},
                'total_entries': 0
            }
            
            # Test each date range
            for range_name, range_start, range_end in date_ranges:
                print(f"\n📅 Testing {range_name}: {range_start.strftime('%Y-%m-%d')} to {range_end.strftime('%Y-%m-%d')}")
                
                # Get time registration
                try:
                    time_reg = await client.get_time_registration(pupil_id, range_start, range_end)
                    print(f"   🕐 Time registration: {len(time_reg)} entries")
                    
                    pupil_data[pupil_id]['time_registrations'][range_name] = time_reg
                    pupil_data[pupil_id]['total_entries'] += len(time_reg)
                    
                    # Show first few entries
                    for i, entry in enumerate(time_reg[:2]):
                        date_str = entry.date.strftime('%m-%d')
                        start_time = entry.start_time.strftime('%H:%M') if entry.start_time else '?'
                        end_time = entry.end_time.strftime('%H:%M') if entry.end_time else '?'
                        reg_type = entry.type if hasattr(entry, 'type') else entry.status or 'unknown'
                        print(f"     - {date_str}: {start_time}-{end_time} ({reg_type})")
                        
                except Exception as e:
                    print(f"   ❌ Error getting time registration: {e}")
                    pupil_data[pupil_id]['time_registrations'][range_name] = []
                
                # Get timetable
                try:
                    timetable = await client.get_timetable(pupil_id, range_start, range_end)
                    print(f"   📚 Timetable: {len(timetable)} entries")
                    
                    pupil_data[pupil_id]['timetables'][range_name] = timetable
                    pupil_data[pupil_id]['total_entries'] += len(timetable)
                    
                except Exception as e:
                    print(f"   ❌ Error getting timetable: {e}")
                    pupil_data[pupil_id]['timetables'][range_name] = []
        
        # Analyze differences
        print(f"\n{'='*60}")
        print("📊 DETAILED PUPIL SWITCHING ANALYSIS")
        print(f"{'='*60}")
        
        pupil_list = list(pupil_data.keys())
        
        if len(pupil_list) >= 2:
            pupil1_id, pupil2_id = pupil_list[0], pupil_list[1]
            pupil1_data = pupil_data[pupil1_id]
            pupil2_data = pupil_data[pupil2_id]
            
            print(f"👤 Pupil 1 ({pupil1_id}): Total entries = {pupil1_data['total_entries']}")
            print(f"👤 Pupil 2 ({pupil2_id}): Total entries = {pupil2_data['total_entries']}")
            
            # Check for differences in each date range
            found_differences = False
            
            for range_name in ["This week", "Last week", "This month"]:
                p1_time_reg = len(pupil1_data['time_registrations'].get(range_name, []))
                p2_time_reg = len(pupil2_data['time_registrations'].get(range_name, []))
                p1_timetable = len(pupil1_data['timetables'].get(range_name, []))
                p2_timetable = len(pupil2_data['timetables'].get(range_name, []))
                
                print(f"\n📅 {range_name}:")
                print(f"   Pupil 1: {p1_time_reg} time reg, {p1_timetable} timetable")
                print(f"   Pupil 2: {p2_time_reg} time reg, {p2_timetable} timetable")
                
                if p1_time_reg != p2_time_reg or p1_timetable != p2_timetable:
                    found_differences = True
                    print(f"   ✅ DIFFERENCE FOUND!")
            
            # Overall assessment
            print(f"\n🎯 SWITCHING ASSESSMENT:")
            if found_differences:
                print("✅ PUPIL SWITCHING IS WORKING!")
                print("   Pupils have different schedules, indicating successful switching.")
                return True
            else:
                print("❌ PUPIL SWITCHING NOT WORKING")
                print("   Both pupils show identical data across all date ranges.")
                
                # Additional debugging
                print(f"\n🔧 DEBUGGING INFO:")
                print(f"   Switch IDs used: {pupil1_data['switch_id']} vs {pupil2_data['switch_id']}")
                print(f"   Are switch IDs different? {pupil1_data['switch_id'] != pupil2_data['switch_id']}")
                
                if pupil1_data['switch_id'] == pupil2_data['switch_id']:
                    print("   ⚠️  Switch IDs are identical - this is the problem!")
                else:
                    print("   ⚠️  Switch IDs are different but data is identical - InfoMentor may not be honoring the switch")
                
                return False
        
        return False

if __name__ == "__main__":
    success = asyncio.run(test_detailed_pupil_switching())
    if success:
        print("\n🚀 Pupil switching confirmed working!")
    else:
        print("\n⚠️  Pupil switching needs further investigation") 
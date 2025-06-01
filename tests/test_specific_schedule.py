#!/usr/bin/env python3
"""
Test script to check the specific schedule scenarios mentioned by the user.
Focus on current week and actual schedule detection.
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

async def test_specific_schedule():
    """Test the specific schedule scenarios."""
    print("📅 Testing Specific Schedule Scenarios")
    print("=" * 60)
    print("User mentioned:")
    print("- Both pupils are off today and tomorrow")  
    print("- One pupil is in Preschool on Monday")
    print("- Other pupil has both School and Fritids on Monday")
    print()
    
    # Try to load credentials from .env file
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials in .env file")
        return
        
    print(f"👤 Testing with username: {username}")
    
    async with InfoMentorClient() as client:
        try:
            # Authenticate
            print("🔐 Authenticating...")
            if not await client.login(username, password):
                print("❌ Authentication failed")
                return
            
            print("✅ Authentication successful!")
            
            pupil_ids = await client.get_pupil_ids()
            print(f"📋 Found {len(pupil_ids)} pupils: {pupil_ids}")
            
            if len(pupil_ids) < 2:
                print("❌ Expected 2 pupils, but found fewer")
                return
            
            # Calculate key dates
            now = datetime.now()
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            
            # Find the upcoming Monday (could be today if today is Monday)
            days_since_monday = today.weekday()  # 0=Monday, 6=Sunday
            if days_since_monday == 0:  # Today is Monday
                next_monday = today
            else:
                next_monday = today + timedelta(days=(7 - days_since_monday))
            
            print(f"📅 Key dates:")
            print(f"   Today: {today.strftime('%A, %Y-%m-%d')}")
            print(f"   Tomorrow: {tomorrow.strftime('%A, %Y-%m-%d')}")
            print(f"   Next Monday: {next_monday.strftime('%A, %Y-%m-%d')}")
            print()
            
            # Get schedules for a range that covers all these dates
            start_date = today - timedelta(days=1)  # Start a day early to be safe
            end_date = next_monday + timedelta(days=7)  # Go a week past Monday
            
            pupils_data = {}
            
            for pupil_id in pupil_ids:
                pupil_info = await client.get_pupil_info(pupil_id)
                pupil_name = pupil_info.name if pupil_info else f"Pupil {pupil_id}"
                
                print(f"👤 Analyzing {pupil_name} (ID: {pupil_id})")
                print("-" * 50)
                
                try:
                    # Get full schedule
                    schedule_days = await client.get_schedule(pupil_id, start_date, end_date)
                    
                    # Create lookup by date
                    schedule_by_date = {}
                    for day in schedule_days:
                        date_key = day.date.date()
                        schedule_by_date[date_key] = day
                    
                    # Store pupil data
                    pupils_data[pupil_id] = {
                        'name': pupil_name,
                        'schedule_by_date': schedule_by_date,
                        'schedule_days': schedule_days
                    }
                    
                    # Check specific dates
                    test_dates = [
                        (today, "Today"),
                        (tomorrow, "Tomorrow"), 
                        (next_monday, "Next Monday")
                    ]
                    
                    for test_date, label in test_dates:
                        date_key = test_date.date()
                        
                        if date_key in schedule_by_date:
                            day = schedule_by_date[date_key]
                            
                            print(f"  📅 {label} ({test_date.strftime('%A, %Y-%m-%d')}):")
                            print(f"     Has school: {day.has_school}")
                            print(f"     Has preschool/fritids: {day.has_preschool_or_fritids}")
                            
                            # Detailed analysis
                            if day.timetable_entries:
                                print(f"     Timetable entries: {len(day.timetable_entries)}")
                                for i, entry in enumerate(day.timetable_entries, 1):
                                    subject = entry.subject or entry.title or "Unknown subject"
                                    time_info = ""
                                    if entry.start_time and entry.end_time:
                                        time_info = f" ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})"
                                    elif entry.is_all_day:
                                        time_info = " (All day)"
                                    print(f"       {i}. {subject}{time_info}")
                            
                            if day.time_registrations:
                                print(f"     Time registrations: {len(day.time_registrations)}")
                                for i, reg in enumerate(day.time_registrations, 1):
                                    time_info = ""
                                    if reg.start_time and reg.end_time:
                                        time_info = f" ({reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')})"
                                    elif reg.start_time:
                                        time_info = f" (from {reg.start_time.strftime('%H:%M')})"
                                    
                                    status_info = f" [{reg.status}]" if reg.status else ""
                                    special_info = ""
                                    if reg.is_school_closed:
                                        special_info = " (School closed)"
                                    elif reg.on_leave:
                                        special_info = " (On leave)"
                                    
                                    print(f"       {i}. Registration{time_info}{status_info}{special_info}")
                            
                            if not day.timetable_entries and not day.time_registrations:
                                print(f"     ✅ No activities (Off day)")
                        else:
                            print(f"  📅 {label} ({test_date.strftime('%A, %Y-%m-%d')}): No data found")
                        
                        print()
                    
                except Exception as e:
                    print(f"  ❌ Error getting schedule: {e}")
                    import traceback
                    traceback.print_exc()
                
                print("=" * 50)
                print()
            
            # Final analysis
            print("🎯 SCENARIO VERIFICATION")
            print("=" * 60)
            
            if len(pupils_data) == 2:
                pupil_list = list(pupils_data.items())
                pupil1_id, pupil1_data = pupil_list[0]
                pupil2_id, pupil2_data = pupil_list[1]
                
                print(f"👤 Pupil 1: {pupil1_data['name']}")
                print(f"👤 Pupil 2: {pupil2_data['name']}")
                print()
                
                # Check today and tomorrow for both
                for test_date, label in [(today, "Today"), (tomorrow, "Tomorrow")]:
                    date_key = test_date.date()
                    
                    print(f"📅 {label} ({test_date.strftime('%A, %Y-%m-%d')}):")
                    
                    for pupil_id, pupil_data in pupils_data.items():
                        pupil_name = pupil_data['name']
                        schedule_by_date = pupil_data['schedule_by_date']
                        
                        if date_key in schedule_by_date:
                            day = schedule_by_date[date_key]
                            is_off = not day.has_school and not day.has_preschool_or_fritids
                            status = "✅ OFF" if is_off else "🔴 HAS ACTIVITIES"
                            print(f"   {pupil_name}: {status}")
                        else:
                            print(f"   {pupil_name}: ❓ No data")
                    print()
                
                # Check Monday for both
                monday_key = next_monday.date()
                print(f"📅 Next Monday ({next_monday.strftime('%A, %Y-%m-%d')}):")
                
                monday_analysis = {}
                for pupil_id, pupil_data in pupils_data.items():
                    pupil_name = pupil_data['name']
                    schedule_by_date = pupil_data['schedule_by_date']
                    
                    if monday_key in schedule_by_date:
                        day = schedule_by_date[monday_key]
                        
                        analysis = {
                            'has_school': day.has_school,
                            'has_preschool_fritids': day.has_preschool_or_fritids,
                            'timetable_count': len(day.timetable_entries),
                            'time_reg_count': len(day.time_registrations)
                        }
                        
                        monday_analysis[pupil_id] = analysis
                        
                        if day.has_school and day.has_preschool_or_fritids:
                            activity_type = "🎒+🏃 School + Fritids"
                        elif day.has_school:
                            activity_type = "🎒 School only"
                        elif day.has_preschool_or_fritids:
                            activity_type = "🧸 Preschool/Fritids only"
                        else:
                            activity_type = "🏠 Off"
                        
                        print(f"   {pupil_name}: {activity_type}")
                        print(f"     - School: {day.has_school} (timetable entries: {len(day.timetable_entries)})")
                        print(f"     - Preschool/Fritids: {day.has_preschool_or_fritids} (time registrations: {len(day.time_registrations)})")
                    else:
                        print(f"   {pupil_name}: ❓ No Monday data")
                
                print()
                print("🎯 Expected vs Actual:")
                print("   Expected: Both off today and tomorrow ✓")
                print("   Expected: One in preschool Monday, other school+fritids Monday")
                
                # Try to match expectations
                if len(monday_analysis) == 2:
                    analyses = list(monday_analysis.values())
                    pupil_names = [pupils_data[pid]['name'] for pid in monday_analysis.keys()]
                    
                    # Look for the patterns
                    preschool_only = []
                    school_plus_fritids = []
                    
                    for i, (pupil_id, analysis) in enumerate(monday_analysis.items()):
                        pupil_name = pupils_data[pupil_id]['name']
                        if analysis['has_preschool_fritids'] and not analysis['has_school']:
                            preschool_only.append(pupil_name)
                        elif analysis['has_school'] and analysis['has_preschool_fritids']:
                            school_plus_fritids.append(pupil_name)
                    
                    if preschool_only and school_plus_fritids:
                        print(f"   ✅ MATCH: {preschool_only[0]} has preschool, {school_plus_fritids[0]} has school+fritids")
                    else:
                        print(f"   ❌ MISMATCH: Pattern not as expected")
                        print(f"      Preschool only: {preschool_only}")
                        print(f"      School+Fritids: {school_plus_fritids}")
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_specific_schedule()) 
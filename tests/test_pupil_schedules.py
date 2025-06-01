#!/usr/bin/env python3
"""
Test script to check the specific schedule scenarios described by the user.
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

async def test_pupil_schedules():
    """Test the specific schedule scenarios described by the user."""
    print("📅 Testing Pupil Schedules")
    print("=" * 50)
    print("Expected scenarios:")
    print("- Both pupils are off today and tomorrow")
    print("- One pupil is in Preschool on Monday")
    print("- Other pupil has both School and Fritids on Monday")
    print()
    
    async with InfoMentorClient() as client:
        username = os.getenv('INFOMENTOR_USERNAME')
        password = os.getenv('INFOMENTOR_PASSWORD')
        
        if not username or not password:
            print("❌ Missing credentials in .env file")
            return
        
        print(f"👤 Testing with username: {username}")
        
        # Authenticate
        if not await client.login(username, password):
            print("❌ Authentication failed")
            return
        
        pupil_ids = await client.get_pupil_ids()
        print(f"📋 Found {len(pupil_ids)} pupils: {pupil_ids}")
        
        # Calculate dates
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        
        # Find next Monday
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:  # Today is Monday
            monday = today
        else:
            monday = today + timedelta(days=days_until_monday)
        
        test_dates = [today, tomorrow, monday]
        date_names = ["Today", "Tomorrow", "Monday"]
        
        print(f"Testing dates:")
        for i, date in enumerate(test_dates):
            print(f"  {date_names[i]}: {date.strftime('%A, %Y-%m-%d')}")
        print()
        
        # Get schedule for a longer period to ensure we capture Monday
        start_date = today
        end_date = today + timedelta(days=10)
        
        for pupil_id in pupil_ids:
            pupil_info = await client.get_pupil_info(pupil_id)
            pupil_name = pupil_info.name if pupil_info else f"Pupil {pupil_id}"
            
            print(f"👤 Testing {pupil_name} (ID: {pupil_id})")
            print("-" * 40)
            
            try:
                # Get schedule
                schedule_days = await client.get_schedule(pupil_id, start_date, end_date)
                
                # Create a lookup dictionary by date
                schedule_by_date = {}
                for day in schedule_days:
                    date_key = day.date.date()
                    schedule_by_date[date_key] = day
                
                # Check each test date
                for i, test_date in enumerate(test_dates):
                    test_date_key = test_date.date()
                    date_name = date_names[i]
                    
                    if test_date_key in schedule_by_date:
                        day = schedule_by_date[test_date_key]
                        
                        print(f"  {date_name} ({test_date.strftime('%A, %Y-%m-%d')}):")
                        print(f"    Has school: {day.has_school}")
                        print(f"    Has preschool/fritids: {day.has_preschool_or_fritids}")
                        
                        # Detailed breakdown
                        if day.timetable_entries:
                            print(f"    Timetable entries ({len(day.timetable_entries)}):")
                            for entry in day.timetable_entries:
                                subject = entry.subject or entry.title or "Unknown"
                                time_str = ""
                                if entry.start_time and entry.end_time:
                                    time_str = f" ({entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')})"
                                elif entry.is_all_day:
                                    time_str = " (All day)"
                                teacher = f" with {entry.teacher}" if entry.teacher else ""
                                room = f" in {entry.room}" if entry.room else ""
                                print(f"      - {subject}{time_str}{teacher}{room}")
                        
                        if day.time_registrations:
                            print(f"    Time registrations ({len(day.time_registrations)}):")
                            for reg in day.time_registrations:
                                time_str = ""
                                if reg.start_time and reg.end_time:
                                    time_str = f" ({reg.start_time.strftime('%H:%M')}-{reg.end_time.strftime('%H:%M')})"
                                elif reg.start_time:
                                    time_str = f" (from {reg.start_time.strftime('%H:%M')})"
                                elif reg.end_time:
                                    time_str = f" (until {reg.end_time.strftime('%H:%M')})"
                                
                                status = f" [{reg.status}]" if reg.status else ""
                                type_info = f" ({reg.type})" if hasattr(reg, 'type') else ""
                                
                                print(f"      - Registration{time_str}{status}{type_info}")
                                
                                if reg.is_school_closed:
                                    print(f"        (School closed: {reg.school_closed_reason or 'No reason given'})")
                                if reg.on_leave:
                                    print(f"        (On leave)")
                                if reg.comment:
                                    print(f"        Comment: {reg.comment}")
                        
                        if not day.timetable_entries and not day.time_registrations:
                            print(f"    ✅ No activities scheduled (as expected for today/tomorrow)")
                    else:
                        print(f"  {date_name} ({test_date.strftime('%A, %Y-%m-%d')}): No schedule data found")
                    
                    print()
                
                # Summary for this pupil
                print(f"  📊 Summary for {pupil_name}:")
                
                # Check today and tomorrow expectations
                today_key = today.date()
                tomorrow_key = tomorrow.date()
                monday_key = monday.date()
                
                today_schedule = schedule_by_date.get(today_key)
                tomorrow_schedule = schedule_by_date.get(tomorrow_key)
                monday_schedule = schedule_by_date.get(monday_key)
                
                # Today expectations
                if today_schedule:
                    expected_off_today = not today_schedule.has_school and not today_schedule.has_preschool_or_fritids
                    print(f"    Today - Expected off: {'✅' if expected_off_today else '❌'}")
                else:
                    print(f"    Today - No data: ⚠️")
                
                # Tomorrow expectations
                if tomorrow_schedule:
                    expected_off_tomorrow = not tomorrow_schedule.has_school and not tomorrow_schedule.has_preschool_or_fritids
                    print(f"    Tomorrow - Expected off: {'✅' if expected_off_tomorrow else '❌'}")
                else:
                    print(f"    Tomorrow - No data: ⚠️")
                
                # Monday analysis
                if monday_schedule:
                    has_school_monday = monday_schedule.has_school
                    has_preschool_fritids_monday = monday_schedule.has_preschool_or_fritids
                    
                    print(f"    Monday - Has school: {'✅' if has_school_monday else '❌'}")
                    print(f"    Monday - Has preschool/fritids: {'✅' if has_preschool_fritids_monday else '❌'}")
                    
                    if has_school_monday and has_preschool_fritids_monday:
                        print(f"    Monday - Type: School + Fritids combination 🎒+🏃")
                    elif has_school_monday:
                        print(f"    Monday - Type: School only 🎒")
                    elif has_preschool_fritids_monday:
                        print(f"    Monday - Type: Preschool/Fritids only 🧸")
                    else:
                        print(f"    Monday - Type: No activities ❌")
                else:
                    print(f"    Monday - No data: ⚠️")
                
            except Exception as e:
                print(f"  ❌ Error getting schedule for {pupil_name}: {e}")
            
            print("=" * 40)
            print()
        
        # Final summary
        print("🎯 FINAL ANALYSIS")
        print("=" * 50)
        print("Based on the schedules retrieved:")
        print("1. Check if both pupils are off today and tomorrow")
        print("2. Identify which pupil has preschool on Monday")
        print("3. Identify which pupil has school + fritids on Monday")
        print()
        print("This will help verify that the schedule detection logic is working correctly.")

if __name__ == "__main__":
    asyncio.run(test_pupil_schedules()) 
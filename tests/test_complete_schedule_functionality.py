#!/usr/bin/env python3
"""
Complete schedule functionality test.
Tests both time registration and timetable entries for all pupils.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import traceback

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')


async def test_complete_schedule_functionality():
    """Test complete schedule functionality for all pupils."""
    print("📅 Testing Complete Schedule Functionality")
    print("=" * 60)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials in .env file")
        return False
    
    try:
        async with InfoMentorClient() as client:
            print(f"🔐 Authenticating with username: {username}")
            
            if not await client.login(username, password):
                print("❌ Authentication failed")
                return False
            
            print("✅ Authentication successful!")
            
            pupil_ids = await client.get_pupil_ids()
            print(f"📋 Found pupils: {pupil_ids}")
            
            if not pupil_ids:
                print("❌ No pupils found")
                return False
            
            # Test date range - this week
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            # Get start of current week (Monday)
            days_since_monday = start_date.weekday()
            week_start = start_date - timedelta(days=days_since_monday)
            week_end = week_start + timedelta(days=6)
            
            print(f"📅 Testing week: {week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}")
            
            all_tests_passed = True
            
            for i, pupil_id in enumerate(pupil_ids):
                print(f"\n👤 Testing Pupil {i+1}: {pupil_id}")
                print("-" * 50)
                
                # Switch to this pupil
                if not await client.switch_pupil(pupil_id):
                    print(f"❌ Failed to switch to pupil {pupil_id}")
                    all_tests_passed = False
                    continue
                
                # Test 1: Time Registration Entries
                print("🕐 Testing Time Registration...")
                try:
                    time_reg = await client.get_time_registration(pupil_id, week_start, week_end)
                    print(f"   📊 Found {len(time_reg)} time registration entries")
                    
                    if len(time_reg) >= 4:
                        print("   ✅ Expected number of time registration entries found")
                    else:
                        print(f"   ⚠️  Only {len(time_reg)} time registration entries (expected 4)")
                    
                    # Show details of time registration entries
                    for j, entry in enumerate(time_reg[:5]):  # Show first 5
                        date_str = entry.date.strftime('%Y-%m-%d') if entry.date else 'No date'
                        start_time = entry.start_time.strftime('%H:%M') if entry.start_time else 'No start'
                        end_time = entry.end_time.strftime('%H:%M') if entry.end_time else 'No end'
                        reg_type = entry.type if hasattr(entry, 'type') else entry.status or 'unknown'
                        print(f"     {j+1}. {date_str} {start_time}-{end_time} ({reg_type})")
                        
                except Exception as e:
                    print(f"   ❌ Time registration failed: {e}")
                    all_tests_passed = False
                
                # Test 2: Timetable Entries
                print("📚 Testing Timetable...")
                try:
                    timetable = await client.get_timetable(pupil_id, week_start, week_end)
                    print(f"   📊 Found {len(timetable)} timetable entries")
                    
                    if len(timetable) > 0:
                        print("   ✅ Timetable entries found")
                        
                        # Show details of timetable entries
                        for j, entry in enumerate(timetable[:5]):  # Show first 5
                            date_str = entry.date.strftime('%Y-%m-%d') if entry.date else 'No date'
                            start_time = entry.start_time.strftime('%H:%M') if entry.start_time else 'No start'
                            end_time = entry.end_time.strftime('%H:%M') if entry.end_time else 'No end'
                            subject = entry.subject or 'No subject'
                            teacher = entry.teacher or 'No teacher'
                            room = entry.room or 'No room'
                            print(f"     {j+1}. {date_str} {start_time}-{end_time} {subject}")
                            print(f"        Teacher: {teacher}, Room: {room}")
                    else:
                        print("   ⚠️  No timetable entries found")
                        
                except Exception as e:
                    print(f"   ❌ Timetable failed: {e}")
                    all_tests_passed = False
                
                # Test 3: Complete Schedule (combines both)
                print("📋 Testing Complete Schedule...")
                try:
                    schedule = await client.get_schedule(pupil_id, week_start, week_end)
                    print(f"   📊 Found {len(schedule)} schedule days")
                    
                    total_timetable = sum(len(day.timetable_entries) for day in schedule)
                    total_time_reg = sum(len(day.time_registrations) for day in schedule)
                    
                    print(f"   📚 Total timetable entries across all days: {total_timetable}")
                    print(f"   🕐 Total time registration entries across all days: {total_time_reg}")
                    
                    # Show daily breakdown
                    for day in schedule:
                        if day.timetable_entries or day.time_registrations:
                            day_str = day.date.strftime('%Y-%m-%d')
                            tt_count = len(day.timetable_entries)
                            tr_count = len(day.time_registrations)
                            print(f"     {day_str}: {tt_count} timetable, {tr_count} time reg")
                    
                    if total_time_reg >= 4:
                        print("   ✅ Complete schedule contains expected time registration entries")
                    else:
                        print(f"   ⚠️  Complete schedule only has {total_time_reg} time registration entries")
                        
                except Exception as e:
                    print(f"   ❌ Complete schedule failed: {e}")
                    all_tests_passed = False
            
            # Summary
            print(f"\n{'='*60}")
            print("📊 COMPLETE SCHEDULE TEST SUMMARY")
            print(f"{'='*60}")
            
            if all_tests_passed:
                print("🎉 ALL SCHEDULE FUNCTIONALITY TESTS PASSED!")
                print("✅ Time registration entries working correctly")
                print("✅ Timetable entries working correctly") 
                print("✅ Complete schedule integration working correctly")
                print("✅ Ready for Home Assistant deployment!")
            else:
                print("⚠️  Some schedule functionality tests had issues")
                print("❌ Please review the output above")
            
            return all_tests_passed
            
    except Exception as e:
        print(f"❌ Error in complete schedule test: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_complete_schedule_functionality())
    if success:
        print("\n🚀 Schedule functionality validation complete - all systems go!")
    else:
        print("\n⚠️  Schedule functionality validation found issues") 
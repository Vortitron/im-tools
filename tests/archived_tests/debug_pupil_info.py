#!/usr/bin/env python3
"""
Debug script to get detailed pupil information.
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

async def debug_pupil_info():
    """Get detailed pupil information."""
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
        
        for i, pupil_id in enumerate(pupil_ids):
            print(f"\n👤 Pupil {i+1}: {pupil_id}")
            print("-" * 40)
            
            try:
                pupil_info = await client.get_pupil_info(pupil_id)
                if pupil_info:
                    print(f"   Name: {pupil_info.name}")
                    print(f"   Class: {pupil_info.class_name}")
                    print(f"   School: {pupil_info.school}")
                else:
                    print("   ⚠️  No detailed pupil info available")
            except Exception as e:
                print(f"   ❌ Error getting pupil info: {e}")
            
            # Check time registration for current month
            start_date = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=31)
            
            print(f"   📅 Checking {start_date.strftime('%Y-%m')} time registrations...")
            try:
                time_reg = await client.get_time_registration(pupil_id, start_date, end_date)
                print(f"   🕐 Found {len(time_reg)} time registration entries this month")
                
                if time_reg:
                    # Show sample entries
                    print("   Sample entries:")
                    for j, entry in enumerate(time_reg[:3]):
                        date_str = entry.date.strftime('%Y-%m-%d')
                        times = f"{entry.start_time.strftime('%H:%M') if entry.start_time else '?'}-{entry.end_time.strftime('%H:%M') if entry.end_time else '?'}"
                        print(f"     {j+1}. {date_str} {times} ({entry.type}) - {entry.status}")
                        
            except Exception as e:
                print(f"   ❌ Error getting time registration: {e}")
            
            print(f"   📚 Checking timetable...")
            try:
                timetable = await client.get_timetable(pupil_id, start_date, end_date)
                print(f"   📊 Found {len(timetable)} timetable entries this month")
                
                if timetable:
                    print("   Sample timetable entries:")
                    for j, entry in enumerate(timetable[:3]):
                        date_str = entry.date.strftime('%Y-%m-%d')
                        subject = entry.subject or 'No subject'
                        times = f"{entry.start_time.strftime('%H:%M') if entry.start_time else '?'}-{entry.end_time.strftime('%H:%M') if entry.end_time else '?'}"
                        print(f"     {j+1}. {date_str} {times} {subject}")
                else:
                    print("   ⚠️  No timetable entries found (likely preschool/fritids only)")
                        
            except Exception as e:
                print(f"   ❌ Error getting timetable: {e}")

if __name__ == "__main__":
    asyncio.run(debug_pupil_info()) 
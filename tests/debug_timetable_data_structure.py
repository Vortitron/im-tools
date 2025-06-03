#!/usr/bin/env python3
"""
Debug script to examine the actual timetable API response structure.
"""

import asyncio
import sys
import os
import json
from pathlib import Path
from datetime import datetime, timedelta

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')

async def debug_timetable_data_structure():
    """Debug the actual structure of timetable API responses."""
    print("🔍 Timetable Data Structure Debug")
    print("=" * 50)
    
    username = os.getenv('INFOMENTOR_USERNAME')
    password = os.getenv('INFOMENTOR_PASSWORD')
    
    if not username or not password:
        print("❌ Missing credentials in .env file")
        return
    
    async with InfoMentorClient() as client:
        print("\n🔐 Authentication")
        print("-" * 20)
        
        try:
            await client.login(username, password)
            print("✅ Authentication successful")
        except Exception as e:
            print(f"❌ Authentication failed: {e}")
            return
        
        # Find Felix
        felix_id = "1806227557"
        print(f"\n🔄 Switching to Felix ({felix_id})")
        print("-" * 30)
        
        try:
            switch_result = await client.switch_pupil(felix_id)
            if not switch_result:
                print(f"❌ Switch failed")
                return
            print(f"✅ Switch successful")
            await asyncio.sleep(2.0)
        except Exception as e:
            print(f"❌ Switch error: {e}")
            return
        
        # Test timetable API with multiple date ranges
        date_ranges = [
            # Current week
            (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0), 
             datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7)),
            # User's specific dates where schedule is missing timetable
            (datetime(2025, 6, 3), datetime(2025, 6, 5)),
            # This week
            (datetime(2025, 6, 2), datetime(2025, 6, 8)),
            # Next week
            (datetime(2025, 6, 9), datetime(2025, 6, 15)),
        ]
        
        for i, (start_date, end_date) in enumerate(date_ranges, 1):
            print(f"\n📅 Test {i}: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            print("-" * 50)
            
            timetable_url = "https://hub.infomentor.se/timetable/timetable/gettimetablelist"
            headers = {
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            
            params = {
                'startDate': start_date.strftime('%Y-%m-%d'),
                'endDate': end_date.strftime('%Y-%m-%d'),
            }
            
            try:
                async with client._session.get(timetable_url, headers=headers, params=params) as resp:
                    print(f"Status: {resp.status}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"Response type: {type(data)}")
                        
                        if isinstance(data, list):
                            print(f"✅ List with {len(data)} items")
                            
                            # Show structure of first few items
                            for j, item in enumerate(data[:3]):
                                print(f"  Item {j+1}: {type(item)}")
                                if isinstance(item, dict):
                                    print(f"    Keys: {list(item.keys())}")
                                    # Show sample values
                                    for key, value in list(item.items())[:5]:
                                        print(f"      {key}: {repr(value)[:50]}...")
                                else:
                                    print(f"    Value: {repr(item)[:100]}...")
                            
                            # Save full data for inspection
                            if data:
                                filename = f"timetable_data_{i}_{start_date.strftime('%Y%m%d')}.json"
                                with open(filename, 'w', encoding='utf-8') as f:
                                    json.dump(data, f, indent=2, default=str)
                                print(f"    💾 Saved to {filename}")
                        
                        elif isinstance(data, dict):
                            print(f"✅ Dict with keys: {list(data.keys())}")
                            
                            # Look for entries in common keys
                            for key in ['entries', 'events', 'items', 'data', 'timetableEntries', 'lessons']:
                                if key in data:
                                    entries = data[key]
                                    print(f"  Found '{key}': {type(entries)} with {len(entries) if hasattr(entries, '__len__') else 'N/A'} items")
                            
                            # Save full data for inspection  
                            filename = f"timetable_data_{i}_{start_date.strftime('%Y%m%d')}.json"
                            with open(filename, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=2, default=str)
                            print(f"    💾 Saved to {filename}")
                        
                        else:
                            print(f"⚠️ Unexpected type: {type(data)}")
                            print(f"   Content: {repr(data)[:200]}...")
                    
                    else:
                        response_text = await resp.text()
                        print(f"❌ HTTP {resp.status}: {response_text[:200]}...")
                        
            except Exception as e:
                print(f"❌ Error: {e}")
        
        print(f"\n🎯 Summary")
        print("-" * 20)
        print("Check the generated JSON files to see the actual timetable data structure.")
        print("This will help us understand if the API returns:")
        print("1. Empty lists (no timetable data)")
        print("2. Lists with timetable entries")
        print("3. Different structure than expected")

if __name__ == "__main__":
    asyncio.run(debug_timetable_data_structure()) 
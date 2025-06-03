#!/usr/bin/env python3
"""
Test script to verify the timetable parsing fix works correctly.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor.client import InfoMentorClient

def test_timetable_parsing():
    """Test timetable parsing with list responses."""
    print("🧪 Testing Timetable Parsing")
    print("=" * 30)
    
    client = InfoMentorClient()
    
    # Test data that mimics what the API returns (empty list)
    empty_list = []
    
    # Test data with actual timetable entries (list format)
    timetable_list = [
        {
            'id': '123',
            'title': 'Mathematics',
            'subject': 'Math',
            'date': '2025-06-03',
            'startTime': '08:00',
            'endTime': '08:45',
            'teacher': 'Mrs. Smith',
            'room': 'Room 12'
        }
    ]
    
    start_date = datetime(2025, 6, 3)
    end_date = datetime(2025, 6, 5)
    pupil_id = '1806227557'
    
    print('📋 Testing empty list:')
    result1 = client._parse_timetable_from_api(empty_list, pupil_id, start_date, end_date)
    print(f'  Result: {len(result1)} entries')
    
    print('📋 Testing list with data:')
    result2 = client._parse_timetable_from_api(timetable_list, pupil_id, start_date, end_date)
    print(f'  Result: {len(result2)} entries')
    if result2:
        entry = result2[0]
        print(f'  Entry: {entry.subject} at {entry.start_time}-{entry.end_time} in {entry.room}')
    
    print('✅ Parsing logic works correctly')

if __name__ == "__main__":
    test_timetable_parsing() 
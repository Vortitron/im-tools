#!/usr/bin/env python3

import asyncio
import os
import sys
sys.path.append('/var/www/im-tools/custom_components/infomentor/infomentor')
from datetime import datetime, timedelta
from client import InfoMentorClient

async def debug_pupil_switching_issue():
    """Debug pupil switching by testing calls without re-switching."""
    username = os.getenv('IM_USERNAME')
    password = os.getenv('IM_PASSWORD')
    
    if not username or not password:
        print('❌ Missing credentials')
        return
    
    print("🔍 DEBUGGING PUPIL SWITCHING ISSUE")
    print("=" * 60)
    
    async with InfoMentorClient() as client:
        if not await client.login(username, password):
            print('❌ Login failed')
            return
        
        pupil_ids = await client.get_pupil_ids()
        print(f'📋 Found pupils: {pupil_ids}')
        
        # Test each pupil separately with direct calls
        week_start = datetime(2025, 5, 26)
        week_end = datetime(2025, 6, 1)
        
        for i, pupil_id in enumerate(pupil_ids):
            print(f'\n👤 Testing Pupil {i+1}: {pupil_id}')
            print('-' * 50)
            
            # First, switch explicitly
            switch_result = await client.switch_pupil(pupil_id)
            print(f'🔄 Switch result: {switch_result}')
            
            # Now call get_time_registration WITHOUT passing pupil_id (to avoid re-switching)
            print("📊 Calling get_time_registration(None, ...) to avoid re-switching")
            time_reg = await client.get_time_registration(None, week_start, week_end)
            print(f'   Found {len(time_reg)} time registration entries')
            
            for j, entry in enumerate(time_reg[:3]):
                date_str = entry.date.strftime('%Y-%m-%d')
                start_time = entry.start_time.strftime('%H:%M') if entry.start_time else 'No start'
                end_time = entry.end_time.strftime('%H:%M') if entry.end_time else 'No end'
                reg_type = entry.type if hasattr(entry, 'type') else entry.status or 'unknown'
                print(f'     {j+1}. {date_str} {start_time}-{end_time} ({reg_type})')
        
        print(f"\n🎯 COMPARISON:")
        print("If pupils show DIFFERENT data = switching works")
        print("If pupils show IDENTICAL data = switching is broken")

if __name__ == "__main__":
    asyncio.run(debug_pupil_switching_issue()) 
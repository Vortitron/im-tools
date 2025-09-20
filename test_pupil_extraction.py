#!/usr/bin/env python3
"""
Test script to test the improved pupil extraction with both pupils and names.
"""

import asyncio
import aiohttp
import os
import sys

# Add the custom_components path to Python path
sys.path.insert(0, '/var/www/im-tools/custom_components/infomentor')

from infomentor.auth import InfoMentorAuth

# Get credentials from environment variables
USERNAME = os.getenv("INFOMENTOR_USERNAME")
PASSWORD = os.getenv("INFOMENTOR_PASSWORD")

if not USERNAME or not PASSWORD:
    print("❌ Please set INFOMENTOR_USERNAME and INFOMENTOR_PASSWORD environment variables")
    exit(1)

async def test_pupil_extraction():
    """Test the improved pupil extraction to find both pupils."""
    print("🔍 Testing improved pupil extraction...")
    
    async with aiohttp.ClientSession() as session:
        auth = InfoMentorAuth(session)
        
        print(f"👤 Testing with username: {USERNAME}")
        
        try:
            success = await auth.login(USERNAME, PASSWORD)
            
            print("=" * 60)
            if success:
                print(f"✅ Authentication successful!")
                print(f"📊 Found {len(auth.pupil_ids)} pupil(s): {auth.pupil_ids}")
                
                # Check if we have pupil switch mappings
                if hasattr(auth, 'pupil_switch_ids') and auth.pupil_switch_ids:
                    print(f"🔗 Pupil switch mappings: {auth.pupil_switch_ids}")
                
                # Expected pupils based on hub dashboard analysis:
                expected_pupils = {
                    "2104025925": "Lyeklint Hancock, Isolde",
                    "1806227557": "Lyeklint Hancock, Felix"
                }
                
                print("\n📋 Expected vs Found:")
                for expected_id, expected_name in expected_pupils.items():
                    if expected_id in auth.pupil_ids:
                        print(f"✅ Found: {expected_id} ({expected_name})")
                    else:
                        print(f"❌ Missing: {expected_id} ({expected_name})")
                
                for found_id in auth.pupil_ids:
                    if found_id not in expected_pupils:
                        print(f"⚠️ Unexpected: {found_id}")
                
                return True
            else:
                print(f"❌ Authentication failed!")
                return False
        except Exception as e:
            print(f"💥 Exception during test: {e}")
            import traceback
            traceback.print_exc()
            return False

async def main():
    """Main test function."""
    print("🚀 Starting pupil extraction test...")
    print("🎯 Expected: 2 pupils (Isolde: 2104025925, Felix: 1806227557)")
    
    success = await test_pupil_extraction()
    
    if success:
        print("\n✅ Test completed!")
    else:
        print("\n❌ Test failed!")

if __name__ == "__main__":
    asyncio.run(main())

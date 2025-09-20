#!/usr/bin/env python3
"""
Test script to verify that pupil names are being stored correctly during authentication.
"""

import asyncio
import aiohttp
import os
import sys

# Add the custom_components path to Python path
sys.path.insert(0, '/var/www/im-tools/custom_components/infomentor')

from infomentor.auth import InfoMentorAuth
from infomentor.client import InfoMentorClient

# Get credentials from environment variables
USERNAME = os.getenv("INFOMENTOR_USERNAME")
PASSWORD = os.getenv("INFOMENTOR_PASSWORD")

if not USERNAME or not PASSWORD:
    print("❌ Please set INFOMENTOR_USERNAME and INFOMENTOR_PASSWORD environment variables")
    exit(1)

async def test_pupil_names():
    """Test that pupil names are being stored and retrieved correctly."""
    print("🔍 Testing pupil name storage and retrieval...")
    
    print(f"👤 Testing with username: {USERNAME}")
    
    try:
        # Use client as async context manager
        async with InfoMentorClient() as client:
            # Login and check pupil names are stored
            success = await client.login(USERNAME, PASSWORD)
            
            print("=" * 60)
            if success:
                print(f"✅ Authentication successful!")
                print(f"📊 Found {len(client.auth.pupil_ids)} pupil(s): {client.auth.pupil_ids}")
                print(f"📝 Stored pupil names: {client.auth.pupil_names}")
                
                # Test get_pupil_info for each pupil
                for pupil_id in client.auth.pupil_ids:
                    print(f"\n🔍 Testing pupil info for {pupil_id}:")
                    pupil_info = await client.get_pupil_info(pupil_id)
                    if pupil_info:
                        print(f"   ✅ Name: {pupil_info.name}")
                        print(f"   📋 ID: {pupil_info.id}")
                    else:
                        print(f"   ❌ No pupil info found")
                
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
    print("🚀 Starting pupil names test...")
    print("🎯 Expected: Both pupils should have their real names stored")
    
    success = await test_pupil_names()
    
    if success:
        print("\n✅ Test completed!")
    else:
        print("\n❌ Test failed!")

if __name__ == "__main__":
    asyncio.run(main())

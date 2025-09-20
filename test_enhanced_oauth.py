#!/usr/bin/env python3
"""
Test script to test the enhanced OAuth flow with LoginCallback handling.
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

async def test_enhanced_oauth_flow():
    """Test the enhanced OAuth flow with LoginCallback detection."""
    print("🚀 Testing enhanced OAuth flow...")
    
    async with aiohttp.ClientSession() as session:
        auth = InfoMentorAuth(session)
        
        print(f"👤 Testing with username: {USERNAME}")
        print("🔍 Enhanced OAuth flow should now detect and handle LoginCallback URLs...")
        
        try:
            success = await auth.login(USERNAME, PASSWORD)
            
            print("=" * 60)
            if success:
                print(f"✅ Enhanced OAuth authentication successful!")
                print(f"📊 Found {len(auth.pupil_ids)} pupil(s): {auth.pupil_ids}")
                return True
            else:
                print(f"❌ Enhanced OAuth authentication failed!")
                return False
        except Exception as e:
            print(f"💥 Exception during enhanced OAuth test: {e}")
            import traceback
            traceback.print_exc()
            return False

async def main():
    """Main test function."""
    print("🚀 Starting enhanced OAuth flow test...")
    print("🎯 This test uses the updated v0.0.53 OAuth flow with LoginCallback handling")
    
    success = await test_enhanced_oauth_flow()
    
    if success:
        print("\n✅ Enhanced OAuth test completed successfully!")
    else:
        print("\n❌ Enhanced OAuth test failed!")
        
    print("\n📁 Check debug files in /tmp/ for detailed OAuth flow analysis:")
    print("   - /tmp/infomentor_debug_initial.html")
    print("   - /tmp/infomentor_debug_oauth.html") 
    print("   - /tmp/infomentor_oauth_callback.html")
    print("   - /tmp/infomentor_oauth_dashboard.html")

if __name__ == "__main__":
    asyncio.run(main())

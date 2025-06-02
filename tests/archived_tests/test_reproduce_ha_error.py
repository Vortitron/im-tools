#!/usr/bin/env python3
"""
Test to reproduce the HTTP 400 error that Home Assistant is getting.
"""

import asyncio
import sys
import json
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
from infomentor.auth import HUB_BASE_URL, DEFAULT_HEADERS
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')

async def test_multiple_scenarios():
    """Test multiple scenarios to try to reproduce HTTP 400."""
    print("🧪 Testing Multiple Scenarios to Reproduce HTTP 400")
    print("=" * 60)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials in .env file")
        return
        
    print(f"👤 Testing with username: {username}")
    
    scenarios = [
        ("Current date", datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)),
        ("Future date", datetime(2025, 6, 2)),
        ("Past date", datetime(2025, 5, 26)),
        ("Current week", datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.now().weekday())),
        ("Invalid date range", datetime(2025, 1, 1)),
    ]
    
    async with InfoMentorClient() as client:
        try:
            print("🔐 Authenticating...")
            if not await client.login(username, password):
                print("❌ Authentication failed")
                return
            
            print("✅ Authentication successful!")
            
            pupil_ids = await client.get_pupil_ids()
            print(f"📋 Found {len(pupil_ids)} pupils: {pupil_ids}")
            
            if not pupil_ids:
                print("❌ No pupils found - trying to continue anyway")
                pupil_ids = ["test"]  # Force continue with dummy ID
            
            for pupil_id in pupil_ids[:1]:  # Test with first pupil only
                print(f"\n👤 Testing with pupil: {pupil_id}")
                
                # Try switching pupil first
                if pupil_id != "test":
                    await client.switch_pupil(pupil_id)
                
                for scenario_name, start_date in scenarios:
                    end_date = start_date + timedelta(days=7)
                    print(f"\n📅 Scenario: {scenario_name} ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})")
                    
                    # Test different request variations
                    variations = [
                        ("Standard request", {}),
                        ("No pupil switch", {"skip_pupil_switch": True}),
                        ("Different headers", {"modified_headers": True}),
                        ("Empty payload", {"empty_payload": True}),
                    ]
                    
                    for var_name, var_options in variations:
                        print(f"  🔬 {var_name}...")
                        
                        try:
                            calendar_entries_url = f"{HUB_BASE_URL}/calendarv2/calendarv2/getentries"
                            headers = DEFAULT_HEADERS.copy()
                            headers.update({
                                "Accept": "application/json, text/javascript, */*; q=0.01",
                                "X-Requested-With": "XMLHttpRequest",
                                "Content-Type": "application/json; charset=UTF-8",
                            })
                            
                            # Modify headers if requested
                            if var_options.get("modified_headers"):
                                headers["User-Agent"] = "HomeAssistant/2024.6.0"
                                headers["Accept"] = "application/json"
                            
                            # Prepare payload
                            if var_options.get("empty_payload"):
                                payload = {}
                            else:
                                payload = {
                                    "startDate": start_date.strftime('%Y-%m-%d'),
                                    "endDate": end_date.strftime('%Y-%m-%d'),
                                }
                            
                            async with client._session.post(calendar_entries_url, headers=headers, json=payload) as resp:
                                response_text = await resp.text()
                                
                                if resp.status == 400:
                                    print(f"    🚨 HTTP 400 REPRODUCED! Response: '{response_text}'")
                                    print(f"    📤 Request headers: {headers}")
                                    print(f"    📤 Request payload: {payload}")
                                    print(f"    📥 Response headers: {dict(resp.headers)}")
                                elif resp.status == 200:
                                    try:
                                        data = json.loads(response_text) if response_text else []
                                        print(f"    ✅ HTTP 200 - Data type: {type(data)}, Length: {len(data) if isinstance(data, list) else 'N/A'}")
                                    except:
                                        print(f"    ✅ HTTP 200 - Raw: '{response_text}'")
                                else:
                                    print(f"    ⚠️ HTTP {resp.status} - Response: '{response_text}'")
                                    
                        except Exception as e:
                            print(f"    ❌ Exception: {e}")
                            
                        # Small delay between requests
                        await asyncio.sleep(0.5)
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

async def test_without_authentication():
    """Test what happens if we make requests without proper authentication."""
    print("\n" + "=" * 60)
    print("🔓 Testing Without Proper Authentication")
    print("=" * 60)
    
    # Create a fresh session without authentication
    async with aiohttp.ClientSession() as session:
        calendar_entries_url = f"{HUB_BASE_URL}/calendarv2/calendarv2/getentries"
        headers = DEFAULT_HEADERS.copy()
        headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json; charset=UTF-8",
        })
        
        payload = {
            "startDate": "2025-06-01",
            "endDate": "2025-06-08",
        }
        
        print(f"🌐 Making unauthenticated request to: {calendar_entries_url}")
        
        try:
            async with session.post(calendar_entries_url, headers=headers, json=payload) as resp:
                response_text = await resp.text()
                print(f"📥 Response status: {resp.status}")
                print(f"📄 Response: '{response_text}'")
                
                if resp.status == 400:
                    print("🚨 HTTP 400 from unauthenticated request!")
                    print(f"📥 Response headers: {dict(resp.headers)}")
        except Exception as e:
            print(f"❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_multiple_scenarios())
    asyncio.run(test_without_authentication()) 
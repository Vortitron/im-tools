#!/usr/bin/env python3
"""
Test to determine the correct HTTP method for calendar entries endpoint.
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

async def test_http_methods():
    """Test different HTTP methods for calendar entries."""
    print("🧪 Testing HTTP Methods for Calendar Entries")
    print("=" * 60)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("❌ Missing credentials in .env file")
        return
        
    print(f"👤 Testing with username: {username}")
    
    async with InfoMentorClient() as client:
        try:
            print("🔐 Authenticating...")
            if not await client.login(username, password):
                print("❌ Authentication failed")
                return
            
            print("✅ Authentication successful!")
            
            pupil_ids = await client.get_pupil_ids()
            print(f"📋 Found {len(pupil_ids)} pupils: {pupil_ids}")
            
            if pupil_ids:
                pupil_id = pupil_ids[0]
                await client.switch_pupil(pupil_id)
                print(f"🔄 Switched to pupil: {pupil_id}")
            
            # Test date range
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=7)
            
            calendar_entries_url = f"{HUB_BASE_URL}/calendarv2/calendarv2/getentries"
            
            # Test data
            date_params = {
                "startDate": start_date.strftime('%Y-%m-%d'),
                "endDate": end_date.strftime('%Y-%m-%d'),
            }
            
            print(f"📅 Testing date range: {date_params}")
            print()
            
            # Test 1: GET with query parameters
            print("🔍 Test 1: GET with query parameters")
            try:
                headers = DEFAULT_HEADERS.copy()
                headers.update({
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                })
                
                async with client._session.get(calendar_entries_url, headers=headers, params=date_params) as resp:
                    response_text = await resp.text()
                    print(f"   Status: {resp.status}")
                    print(f"   Response: {response_text[:100]}...")
                    
                    if resp.status == 200:
                        try:
                            data = json.loads(response_text) if response_text else []
                            print(f"   ✅ GET success! Data type: {type(data)}, Length: {len(data) if isinstance(data, list) else 'N/A'}")
                        except:
                            print(f"   ✅ GET success! Raw response")
                    else:
                        print(f"   ❌ GET failed")
            except Exception as e:
                print(f"   ❌ GET exception: {e}")
            
            print()
            
            # Test 2: POST with JSON payload
            print("🔍 Test 2: POST with JSON payload")
            try:
                headers = DEFAULT_HEADERS.copy()
                headers.update({
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json; charset=UTF-8",
                })
                
                async with client._session.post(calendar_entries_url, headers=headers, json=date_params) as resp:
                    response_text = await resp.text()
                    print(f"   Status: {resp.status}")
                    print(f"   Response: {response_text[:100]}...")
                    
                    if resp.status == 200:
                        try:
                            data = json.loads(response_text) if response_text else []
                            print(f"   ✅ POST success! Data type: {type(data)}, Length: {len(data) if isinstance(data, list) else 'N/A'}")
                        except:
                            print(f"   ✅ POST success! Raw response")
                    else:
                        print(f"   ❌ POST failed")
                        print(f"   Headers: {dict(resp.headers)}")
            except Exception as e:
                print(f"   ❌ POST exception: {e}")
            
            print()
            
            # Test 3: POST with form data
            print("🔍 Test 3: POST with form data")
            try:
                headers = DEFAULT_HEADERS.copy()
                headers.update({
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded",
                })
                
                async with client._session.post(calendar_entries_url, headers=headers, data=date_params) as resp:
                    response_text = await resp.text()
                    print(f"   Status: {resp.status}")
                    print(f"   Response: {response_text[:100]}...")
                    
                    if resp.status == 200:
                        try:
                            data = json.loads(response_text) if response_text else []
                            print(f"   ✅ POST form success! Data type: {type(data)}, Length: {len(data) if isinstance(data, list) else 'N/A'}")
                        except:
                            print(f"   ✅ POST form success! Raw response")
                    else:
                        print(f"   ❌ POST form failed")
            except Exception as e:
                print(f"   ❌ POST form exception: {e}")
            
            print()
            
            # Test 4: Different endpoint variations
            print("🔍 Test 4: Endpoint variations")
            endpoint_variations = [
                f"{HUB_BASE_URL}/calendarv2/calendarv2/getentries/",  # With trailing slash
                f"{HUB_BASE_URL}/CalendarV2/CalendarV2/GetEntries",   # Different case
                f"{HUB_BASE_URL}/calendarv2/getentries",              # Shorter path
            ]
            
            for i, url in enumerate(endpoint_variations, 1):
                print(f"   Variation {i}: {url}")
                try:
                    headers = DEFAULT_HEADERS.copy()
                    headers.update({
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                    })
                    
                    async with client._session.get(url, headers=headers, params=date_params) as resp:
                        print(f"      Status: {resp.status}")
                        if resp.status == 200:
                            response_text = await resp.text()
                            try:
                                data = json.loads(response_text) if response_text else []
                                print(f"      ✅ Success! Data type: {type(data)}")
                            except:
                                print(f"      ✅ Success! Non-JSON response")
                        else:
                            print(f"      ❌ Failed")
                except Exception as e:
                    print(f"      ❌ Exception: {e}")
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_http_methods()) 
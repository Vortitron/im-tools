#!/usr/bin/env python3
"""
Quick test to see if JSON API endpoints work after two-stage OAuth authentication.
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.resolve() / 'custom_components' / 'infomentor'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

from infomentor import InfoMentorClient

async def test_json_apis_after_auth():
	"""Test if JSON APIs work after authentication."""
	print("🧪 Quick JSON API Test")
	print("=" * 30)
	
	username = os.getenv('INFOMENTOR_USERNAME')
	password = os.getenv('INFOMENTOR_PASSWORD')
	
	async with InfoMentorClient() as client:
		print("🔐 Authenticating...")
		if await client.login(username, password):
			print("✅ Authentication successful!")
			
			pupil_ids = await client.get_pupil_ids()
			print(f"👥 Found pupil IDs: {pupil_ids}")
			
			if pupil_ids:
				# Test JSON API with first pupil
				pupil_id = pupil_ids[0]
				print(f"\n📅 Testing JSON APIs with pupil: {pupil_id}")
				
				start_date = datetime.now() - timedelta(days=1)
				end_date = datetime.now() + timedelta(days=5)
				
				# Test calendar API
				try:
					url = "https://hub.infomentor.se/calendarv2/calendarv2/getentries"
					headers = {
						"Accept": "application/json",
						"X-Requested-With": "XMLHttpRequest",
						"Content-Type": "application/json",
					}
					
					payload = {
						"startDate": start_date.strftime('%Y-%m-%d'),
						"endDate": end_date.strftime('%Y-%m-%d'),
					}
					
					print(f"🔍 Testing calendar API...")
					async with client._session.post(url, headers=headers, json=payload) as resp:
						print(f"   Status: {resp.status}")
						if resp.status == 200:
							data = await resp.json()
							print(f"   ✅ JSON API works! Got {len(data) if isinstance(data, list) else 'data'}")
							return True
						else:
							print(f"   ❌ API failed: {resp.status}")
							text = await resp.text()
							print(f"   Response: {text[:100]}...")
							
				except Exception as e:
					print(f"   ❌ Error: {e}")
		else:
			print("❌ Authentication failed")
	
	return False

if __name__ == "__main__":
	asyncio.run(test_json_apis_after_auth()) 
#!/usr/bin/env python3
"""Debug authentication and pupil ID extraction."""

import asyncio
import sys
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve() / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

async def test_auth():
    async with InfoMentorClient() as client:
        username = os.getenv('INFOMENTOR_USERNAME')
        password = os.getenv('INFOMENTOR_PASSWORD')
        
        if await client.login(username, password):
            print('✅ Auth succeeded')
            pupil_ids = await client.get_pupil_ids()
            print(f'Pupil IDs: {pupil_ids}')
            
            # Try to get the hub page content to see what we're getting
            hub_url = 'https://hub.infomentor.se/#/'
            headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0'}
            async with client._session.get(hub_url, headers=headers) as resp:
                text = await resp.text()
                print(f'Hub page status: {resp.status}')
                print(f'Hub page content (first 1000 chars): {text[:1000]}')
                
                # Save for analysis
                with open('hub_page_debug.html', 'w', encoding='utf-8') as f:
                    f.write(text)
                print('💾 Saved hub page to hub_page_debug.html')
                
                # Look for pupil patterns
                patterns = [
                    r'/SwitchPupil/(\d+)',
                    r'SwitchPupil/(\d+)', 
                    r'pupil[^0-9]*(\d+)',
                    r'PupilSwitcher[^0-9]*(\d+)',
                    r'/Account/PupilSwitcher/SwitchPupil/(\d+)',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    if matches:
                        print(f'Pattern {pattern} found: {matches}')
        else:
            print('❌ Auth failed')

asyncio.run(test_auth()) 
#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))
from infomentor import InfoMentorClient
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

async def test():
    async with InfoMentorClient() as client:
        print('Auth starting...')
        result = await client.login(os.getenv('INFOMENTOR_USERNAME'), os.getenv('INFOMENTOR_PASSWORD'))
        print(f'Auth result: {result}')
        pupils = await client.get_pupil_ids()
        print(f'Pupils: {pupils}')
        print(f'Switch mapping: {client.auth.pupil_switch_ids}')

asyncio.run(test()) 
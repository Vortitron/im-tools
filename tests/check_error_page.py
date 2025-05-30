#!/usr/bin/env python3
import asyncio
import aiohttp

async def check_error_page():
    url = 'https://infomentor.se/Swedish/Production/mentor/Villa.aspx?aspxerrorpath=/Swedish/Production/mentor/Oryggi/Login.aspx'
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0'}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            print(f'Status: {resp.status}')
            text = await resp.text()
            print(f'Content: {text}')

asyncio.run(check_error_page()) 
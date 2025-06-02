#!/usr/bin/env python3
"""
Simple test suite for validating the time registration fix.
Tests the key aspects without requiring pytest.
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import traceback

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
from infomentor.auth import HUB_BASE_URL
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')


class MockResponse:
    """Simple mock response class."""
    def __init__(self, status, json_data=None, text_data=None):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data or ""
        self.headers = {}
    
    async def json(self):
        return self._json_data
    
    async def text(self):
        return self._text_data
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


async def test_authentication_validation():
    """Test that proper authentication validation is performed."""
    print("🔐 Testing Authentication Validation")
    print("=" * 50)
    
    test_results = []
    
    try:
        client = InfoMentorClient()
        
        # Test 1: No auth object
        client.authenticated = False
        client.auth = None
        result = await client.get_time_registration()
        assert result == [], "Should return empty list when auth is None"
        test_results.append("✅ Test 1: Handles missing auth object")
        
        # Test 2: Auth not authenticated
        client.authenticated = False
        client.auth = MagicMock()
        client.auth.authenticated = False
        client.auth.pupil_ids = ["test"]
        result = await client.get_time_registration()
        assert result == [], "Should return empty list when not authenticated"
        test_results.append("✅ Test 2: Handles unauthenticated state")
        
        # Test 3: No pupil IDs
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = []
        result = await client.get_time_registration()
        assert result == [], "Should return empty list when no pupil IDs"
        test_results.append("✅ Test 3: Handles missing pupil IDs")
        
        if hasattr(client, '_session') and client._session:
            await client._session.close()
        
    except Exception as e:
        test_results.append(f"❌ Authentication validation test failed: {e}")
        traceback.print_exc()
    
    for result in test_results:
        print(result)
    
    return len([r for r in test_results if r.startswith("✅")]) == 3


async def test_get_first_approach():
    """Test that GET requests are attempted first."""
    print("\n🔄 Testing GET-First Approach")
    print("=" * 50)
    
    try:
        client = InfoMentorClient()
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        
        # Create mock session
        mock_session = AsyncMock()
        client._session = mock_session
        
        # Mock successful GET response
        mock_response = MockResponse(200, {"result": []})
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Mock the _ensure_authenticated method to bypass authentication check
        with patch.object(client, '_ensure_authenticated', return_value=None):
            await client.get_time_registration()
        
        # Verify GET was called
        assert mock_session.get.called, "GET request should be attempted first"
        assert not mock_session.post.called, "POST should not be called when GET succeeds"
        
        # Check the URL contains the expected endpoint
        call_args = mock_session.get.call_args
        assert "/TimeRegistration/GetTimeRegistrations/" in str(call_args), "Should call correct endpoint"
        
        print("✅ GET request attempted first with correct endpoint")
        
        if hasattr(client, '_session') and client._session:
            await client._session.close()
        return True
        
    except Exception as e:
        print(f"❌ GET-first approach test failed: {e}")
        traceback.print_exc()
        return False


async def test_post_fallback_on_invalid_verb():
    """Test that POST fallback is triggered on 'Invalid Verb' errors."""
    print("\n🔄 Testing POST Fallback on Invalid Verb")
    print("=" * 50)
    
    try:
        client = InfoMentorClient()
        client.authenticated = True
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        
        # Create mock session
        mock_session = AsyncMock()
        client._session = mock_session
        
        # Mock GET response with "Invalid Verb" error
        mock_get_response = MockResponse(400, text_data="Invalid Verb: GET not supported")
        
        # Mock successful POST response
        mock_post_response = MockResponse(200, {"result": []})
        
        # Set up call sequence - both GET endpoints fail, then POST succeeds
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_get_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
        
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_post_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Mock the _ensure_authenticated method to bypass authentication check
        with patch.object(client, '_ensure_authenticated', return_value=None):
            await client.get_time_registration()
        
        # Verify both GET and POST were called
        assert mock_session.get.called, "GET should be attempted first"
        assert mock_session.post.called, "POST should be attempted as fallback"
        
        print("✅ POST fallback triggered correctly on Invalid Verb error")
        
        if hasattr(client, '_session') and client._session:
            await client._session.close()
        return True
        
    except Exception as e:
        print(f"❌ POST fallback test failed: {e}")
        traceback.print_exc()
        return False


async def test_authentication_error_handling():
    """Test proper handling of HTTP 401/403 authentication errors."""
    print("\n🔐 Testing Authentication Error Handling")
    print("=" * 50)
    
    results = []
    
    try:
        for status_code in [401, 403]:
            client = InfoMentorClient()
            client.authenticated = True
            client.auth = MagicMock()
            client.auth.authenticated = True
            client.auth.pupil_ids = ["test_pupil"]
            
            # Create mock session
            mock_session = AsyncMock()
            client._session = mock_session
            
            # Mock authentication error response
            mock_response = MockResponse(status_code, text_data=f"HTTP {status_code} Unauthorized")
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Mock the _ensure_authenticated method to bypass authentication check
            with patch.object(client, '_ensure_authenticated', return_value=None):
                result = await client.get_time_registration()
            
            # Should return empty list and not attempt POST fallback
            assert result == [], f"Should return empty list on HTTP {status_code}"
            assert not mock_session.post.called, f"Should not attempt POST fallback on HTTP {status_code}"
            
            results.append(f"✅ HTTP {status_code} handled correctly (no POST fallback)")
            
            if hasattr(client, '_session') and client._session:
                await client._session.close()
    
    except Exception as e:
        results.append(f"❌ Authentication error handling test failed: {e}")
        traceback.print_exc()
    
    for result in results:
        print(result)
    
    return len(results) == 2 and all(r.startswith("✅") for r in results)


async def test_real_authentication_if_available():
    """Test with real credentials if available."""
    print("\n🌐 Testing Real Authentication Flow")
    print("=" * 50)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("⚠️  Skipping real authentication test - no credentials in .env")
        return True  # Skip but don't fail
    
    try:
        client = InfoMentorClient()
        print(f"🔐 Authenticating with username: {username}")
        
        if not await client.login(username, password):
            print("❌ Authentication failed")
            return False
        
        print("✅ Authentication successful!")
        
        # Test authentication validation
        if not client.auth or not client.auth.authenticated or not client.auth.pupil_ids:
            print("❌ Authentication validation failed")
            return False
        
        pupil_ids = await client.get_pupil_ids()
        print(f"📋 Found pupils: {pupil_ids}")
        
        if pupil_ids:
            pupil_id = pupil_ids[0]
            print(f"🧪 Testing time registration for pupil: {pupil_id}")
            
            # Test the fixed method
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=3)
            
            time_reg = await client.get_time_registration(pupil_id, start_date, end_date)
            print(f"📊 Retrieved {len(time_reg)} time registration entries")
            
            print("✅ Real authentication flow completed successfully")
            return True
        else:
            print("⚠️  No pupils found, but authentication worked")
            return True
            
    except Exception as e:
        print(f"❌ Error in real authentication test: {e}")
        traceback.print_exc()
        return False
    finally:
        if 'client' in locals() and hasattr(client, '_session') and client._session:
            await client._session.close()


async def run_all_tests():
    """Run all tests and report results."""
    print("🧪 Time Registration Fix Test Suite")
    print("=" * 60)
    
    tests = [
        ("Authentication Validation", test_authentication_validation),
        ("GET-First Approach", test_get_first_approach),
        ("POST Fallback on Invalid Verb", test_post_fallback_on_invalid_verb),
        ("Authentication Error Handling", test_authentication_error_handling),
        ("Real Authentication Flow", test_real_authentication_if_available),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} threw an exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
        if result:
            passed += 1
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The time registration fix appears to be working correctly.")
    else:
        print("⚠️  Some tests failed. Please review the output above.")
    
    return passed == total


if __name__ == "__main__":
    asyncio.run(run_all_tests()) 
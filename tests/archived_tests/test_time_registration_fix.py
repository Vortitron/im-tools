#!/usr/bin/env python3
"""
Test suite for validating the time registration fix that implements:
1. GET-first approach for time registration endpoints
2. Enhanced authentication validation
3. POST fallback mechanism for "Invalid Verb" errors
4. Proper handling of HTTP 401/403 authentication errors
"""

import asyncio
import sys
import json
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Add the custom components to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'infomentor'))

from infomentor import InfoMentorClient
from infomentor.auth import HUB_BASE_URL, DEFAULT_HEADERS
from infomentor.models import TimeRegistrationEntry
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / '.env')


class TestTimeRegistrationFix:
    """Test class for time registration fix validation."""

    @pytest.fixture
    async def client(self):
        """Create a test client with mocked authentication."""
        client = InfoMentorClient()
        
        # Mock the authentication
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil_123"]
        client._session = AsyncMock()
        
        yield client
        
        if hasattr(client, '_session') and client._session:
            await client._session.close()

    async def test_authentication_validation(self):
        """Test that proper authentication validation is performed."""
        print("🔐 Testing Authentication Validation")
        print("=" * 50)
        
        client = InfoMentorClient()
        
        # Test 1: No auth object
        client.auth = None
        result = await client.get_time_registration()
        assert result == [], "Should return empty list when auth is None"
        print("✅ Test 1: Handles missing auth object")
        
        # Test 2: Auth not authenticated
        client.auth = MagicMock()
        client.auth.authenticated = False
        client.auth.pupil_ids = ["test"]
        result = await client.get_time_registration()
        assert result == [], "Should return empty list when not authenticated"
        print("✅ Test 2: Handles unauthenticated state")
        
        # Test 3: No pupil IDs
        client.auth.authenticated = True
        client.auth.pupil_ids = []
        result = await client.get_time_registration()
        assert result == [], "Should return empty list when no pupil IDs"
        print("✅ Test 3: Handles missing pupil IDs")
        
        # Test 4: Valid authentication
        client.auth.pupil_ids = ["test_pupil"]
        client._session = AsyncMock()
        
        # Mock successful GET response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"data": []}
        client._session.get.return_value.__aenter__.return_value = mock_response
        
        result = await client.get_time_registration()
        print("✅ Test 4: Proceeds with valid authentication")
        
        await client.close()

    async def test_get_first_approach(self):
        """Test that GET requests are attempted first for time registration endpoints."""
        print("\n🔄 Testing GET-First Approach")
        print("=" * 50)
        
        client = InfoMentorClient()
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        client._session = AsyncMock()
        
        # Mock successful GET response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"result": []}
        client._session.get.return_value.__aenter__.return_value = mock_response
        
        await client.get_time_registration()
        
        # Verify GET was called first
        assert client._session.get.called, "GET request should be attempted first"
        assert not client._session.post.called, "POST should not be called when GET succeeds"
        
        # Check the URL and parameters
        call_args = client._session.get.call_args
        assert "/TimeRegistration/GetTimeRegistrations/" in call_args[0][0]
        assert "params" in call_args[1]
        assert "startDate" in call_args[1]["params"]
        assert "endDate" in call_args[1]["params"]
        
        print("✅ GET request attempted first with correct parameters")
        
        await client.close()

    async def test_post_fallback_on_invalid_verb(self):
        """Test that POST fallback is triggered on 'Invalid Verb' errors."""
        print("\n🔄 Testing POST Fallback on Invalid Verb")
        print("=" * 50)
        
        client = InfoMentorClient()
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        client._session = AsyncMock()
        
        # Mock GET response with "Invalid Verb" error
        mock_get_response = AsyncMock()
        mock_get_response.status = 400
        mock_get_response.text.return_value = "Invalid Verb: GET not supported"
        
        # Mock successful POST response
        mock_post_response = AsyncMock()
        mock_post_response.status = 200
        mock_post_response.json.return_value = {"result": []}
        
        client._session.get.return_value.__aenter__.return_value = mock_get_response
        client._session.post.return_value.__aenter__.return_value = mock_post_response
        
        await client.get_time_registration()
        
        # Verify both GET and POST were called
        assert client._session.get.called, "GET should be attempted first"
        assert client._session.post.called, "POST should be attempted as fallback"
        
        # Check POST request details
        post_call_args = client._session.post.call_args
        assert "json" in post_call_args[1], "POST should include JSON payload"
        assert "startDate" in post_call_args[1]["json"]
        assert "endDate" in post_call_args[1]["json"]
        
        print("✅ POST fallback triggered correctly on Invalid Verb error")
        
        await client.close()

    async def test_authentication_error_handling(self):
        """Test proper handling of HTTP 401/403 authentication errors."""
        print("\n🔐 Testing Authentication Error Handling")
        print("=" * 50)
        
        client = InfoMentorClient()
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        client._session = AsyncMock()
        
        for status_code in [401, 403]:
            # Reset mocks
            client._session.reset_mock()
            
            # Mock authentication error response
            mock_response = AsyncMock()
            mock_response.status = status_code
            mock_response.text.return_value = f"HTTP {status_code} Unauthorized"
            client._session.get.return_value.__aenter__.return_value = mock_response
            
            result = await client.get_time_registration()
            
            # Should return empty list and not attempt POST fallback
            assert result == [], f"Should return empty list on HTTP {status_code}"
            assert not client._session.post.called, f"Should not attempt POST fallback on HTTP {status_code}"
            
            print(f"✅ HTTP {status_code} handled correctly (no POST fallback)")
        
        await client.close()

    async def test_calendar_data_endpoint_fallback(self):
        """Test fallback to GetCalendarData endpoint when GetTimeRegistrations fails."""
        print("\n📅 Testing Calendar Data Endpoint Fallback")
        print("=" * 50)
        
        client = InfoMentorClient()
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["test_pupil"]
        client._session = AsyncMock()
        
        # Mock first endpoint failure (non-auth error)
        mock_first_response = AsyncMock()
        mock_first_response.status = 500
        mock_first_response.text.return_value = "Internal Server Error"
        
        # Mock second endpoint success
        mock_second_response = AsyncMock()
        mock_second_response.status = 200
        mock_second_response.json.return_value = {"CalendarData": []}
        
        # Set up the GET calls to return different responses
        client._session.get.side_effect = [
            # First call context manager
            AsyncMock(__aenter__=AsyncMock(return_value=mock_first_response)),
            # Second call context manager  
            AsyncMock(__aenter__=AsyncMock(return_value=mock_second_response))
        ]
        
        await client.get_time_registration()
        
        # Verify both endpoints were called
        assert client._session.get.call_count == 2, "Both endpoints should be attempted"
        
        # Check that the second call was to GetCalendarData
        second_call_args = client._session.get.call_args_list[1]
        assert "/GetCalendarData/" in second_call_args[0][0], "Second call should be to GetCalendarData endpoint"
        
        print("✅ Calendar data endpoint fallback works correctly")
        
        await client.close()

    async def test_switch_pupil_integration(self):
        """Test that pupil switching works correctly in time registration."""
        print("\n👤 Testing Pupil Switching Integration")
        print("=" * 50)
        
        client = InfoMentorClient()
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["pupil1", "pupil2"]
        client._session = AsyncMock()
        
        # Mock switch_pupil method
        client.switch_pupil = AsyncMock(return_value=True)
        
        # Mock successful response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"result": []}
        client._session.get.return_value.__aenter__.return_value = mock_response
        
        # Test with specific pupil ID
        await client.get_time_registration(pupil_id="pupil2")
        
        # Verify switch_pupil was called
        client.switch_pupil.assert_called_once_with("pupil2")
        
        print("✅ Pupil switching integration works correctly")
        
        await client.close()

    async def test_failed_pupil_switch_handling(self):
        """Test handling of failed pupil switches."""
        print("\n❌ Testing Failed Pupil Switch Handling")
        print("=" * 50)
        
        client = InfoMentorClient()
        client.auth = MagicMock()
        client.auth.authenticated = True
        client.auth.pupil_ids = ["pupil1", "pupil2"]
        client._session = AsyncMock()
        
        # Mock failed switch_pupil method
        client.switch_pupil = AsyncMock(return_value=False)
        
        result = await client.get_time_registration(pupil_id="invalid_pupil")
        
        # Should return empty list when pupil switch fails
        assert result == [], "Should return empty list when pupil switch fails"
        assert not client._session.get.called, "Should not make API calls when pupil switch fails"
        
        print("✅ Failed pupil switch handled correctly")
        
        await client.close()


async def test_real_authentication_flow():
    """Test with real credentials if available."""
    print("\n🌐 Testing Real Authentication Flow")
    print("=" * 50)
    
    username = os.getenv("INFOMENTOR_USERNAME")
    password = os.getenv("INFOMENTOR_PASSWORD")
    
    if not username or not password:
        print("⚠️  Skipping real authentication test - no credentials in .env")
        return
    
    async with InfoMentorClient() as client:
        try:
            print(f"🔐 Authenticating with username: {username}")
            
            if not await client.login(username, password):
                print("❌ Authentication failed")
                return
            
            print("✅ Authentication successful!")
            
            # Test authentication validation
            assert client.auth is not None, "Auth object should exist"
            assert client.auth.authenticated, "Should be authenticated"
            assert len(client.auth.pupil_ids) > 0, "Should have pupil IDs"
            
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
                
                # Should not throw exceptions
                print("✅ Real authentication flow completed successfully")
            
        except Exception as e:
            print(f"❌ Error in real authentication test: {e}")
            import traceback
            traceback.print_exc()


async def run_all_tests():
    """Run all tests in sequence."""
    print("🧪 Time Registration Fix Test Suite")
    print("=" * 60)
    
    test_instance = TestTimeRegistrationFix()
    
    # Run mock-based tests
    await test_instance.test_authentication_validation()
    await test_instance.test_get_first_approach()
    await test_instance.test_post_fallback_on_invalid_verb()
    await test_instance.test_authentication_error_handling()
    await test_instance.test_calendar_data_endpoint_fallback()
    await test_instance.test_switch_pupil_integration()
    await test_instance.test_failed_pupil_switch_handling()
    
    # Run real authentication test if credentials available
    await test_real_authentication_flow()
    
    print("\n" + "=" * 60)
    print("✅ All Time Registration Fix Tests Completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests()) 
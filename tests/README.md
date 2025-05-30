# Tests Directory

This directory contains all test and debugging scripts for the InfoMentor Home Assistant integration.

## Structure

### Test Scripts
- `test_*.py` - Main test scripts for various components
- `debug_*.py` - Debug scripts for troubleshooting specific issues
- `trace_*.py` - Scripts for tracing OAuth flows and API calls
- `quick_*.py` - Quick verification scripts
- `check_*.py` - Error checking scripts

### Categories

#### Authentication Tests
- `test_auth_debug.py` - Basic authentication debugging
- `test_modern_auth.py` - Modern OAuth flow testing
- `test_complete_oauth_credentials.py` - Complete OAuth credential testing
- `debug_auth_flow.py` - OAuth flow debugging
- `trace_oauth_flow.py` - OAuth flow tracing

#### API Tests
- `test_api_parsing.py` - API response parsing tests
- `test_infomentor.py` - Core InfoMentor API tests
- `test_infomentor_complete.py` - Complete InfoMentor integration tests
- `test_kids_info.py` - Children's information retrieval tests
- `quick_api_test.py` - Quick API verification

#### Debug Scripts
- `debug_infomentor.py` - General InfoMentor debugging
- `debug_pupil_names.py` - Pupil name extraction debugging
- `debug_session_expired.py` - Session expiry handling
- `debug_html_capture.py` - HTML page capture for debugging
- `check_error_page.py` - Error page checking

## Running Tests

### Prerequisites
```bash
pip install -r test_requirements.txt
```

### Environment Setup
Ensure you have a `.env` file in the root directory with your InfoMentor credentials:
```
IM_USERNAME=your_username
IM_PASSWORD=your_password
```

### Running Individual Tests
```bash
# From the root directory
python tests/test_infomentor.py

# Or from the tests directory
cd tests
python test_infomentor.py
```

### Running All Tests
```bash
# Use the test runner (if created)
python run_tests.py
```

## Output

Test results and debug output are automatically saved to `/debug_output/` which is included in `.gitignore`.

## Notes

- All HTML captures and debug output are stored in `/debug_output/`
- Tests may require valid InfoMentor credentials
- Some tests may take time due to OAuth flows and API calls
- Check the individual test files for specific requirements and usage 
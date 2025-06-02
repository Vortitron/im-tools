# InfoMentor Tests

This directory contains tests for the InfoMentor Home Assistant integration.

## Main Tests

### 🚀 **test_all_kids_comprehensive.py** (RECOMMENDED)
**The primary test for getting timeregistration and timetable data for all children.**

This comprehensive test:
- Authenticates with InfoMentor
- Discovers all children in the account
- Gets timetable data for each child
- Gets time registration data for each child  
- Gets combined schedule data for each child
- Determines child type (school vs preschool) based on timetable entries
- Saves all data to JSON files for analysis
- Provides clear summary output

**Status**: ✅ **WORKING** - Pupil switching issue resolved! Now correctly retrieves different data for each child.

Usage:
```bash
python3 test_all_kids_comprehensive.py
```

### Other Useful Tests

- **test_infomentor_complete.py** - Complete API endpoint testing
- **test_kids_info.py** - Detailed child information and type detection
- **test_complete_schedule_functionality.py** - Schedule functionality testing
- **test_infomentor.py** - Basic InfoMentor client testing
- **quick_api_test.py** - Quick API connectivity test

## Archived Tests

Older debug and development tests have been moved to `archived_tests/` directory to keep the main tests directory tidy. These include:
- Debug scripts for specific issues
- OAuth flow debugging
- Time registration fix attempts
- Pupil switching debugging
- HTTP method testing

## Requirements

Install test dependencies:
```bash
pip install -r test_requirements.txt
```

## Environment Setup

Create a `.env` file in the project root with:
```
INFOMENTOR_USERNAME=your_username
INFOMENTOR_PASSWORD=your_password
```

Or the tests will prompt for credentials interactively.

## Output

Test results are saved to `debug_output/` directory with timestamped filenames for analysis.

## Running Tests

For the comprehensive test (recommended):
```bash
python3 test_all_kids_comprehensive.py
```

For all tests:
```bash
python3 run_tests.py
``` 
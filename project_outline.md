# InfoMentor Home Assistant Integration - Project Outline

## Overview
A comprehensive Home Assistant integration for InfoMentor school communication platform, providing real-time access to school schedules, news, and timeline entries for Swedish families.

## Architecture

### Core Components

#### 1. Authentication (`auth.py`)
- OAuth-based authentication with InfoMentor
- Session management and token refresh
- Multi-pupil account support

#### 2. API Client (`client.py`)
- RESTful API interface to InfoMentor endpoints
- **Timetable Endpoint**: `/timetable/timetable/gettimetablelist` for school lessons
- **Time Registration**: `/TimeRegistration/TimeRegistration/GetTimeRegistrations/` for preschool/fritids
- Robust error handling and fallback mechanisms
- Pupil switching capabilities

#### 3. Data Models (`models.py`)
- **TimetableEntry**: School lessons and educational activities
- **TimeRegistrationEntry**: Preschool/fritids care registrations  
- **ScheduleDay**: Complete daily schedule combining both types
- **NewsItem**, **TimelineEntry**: Communication from school
- **PupilInfo**: Student information

#### 4. Home Assistant Integration
- **Coordinator**: Data update coordination (30-minute intervals)
- **Sensors**: Multiple sensor types per pupil
- **Config Flow**: User-friendly setup via UI

### Key Data Properties

#### Schedule Day Properties
- **`has_school`**: ANY scheduled activity (lessons OR care)
- **`has_timetable_entries`**: Only actual school lessons 
- **`has_preschool_or_fritids`**: Time registrations for care

This distinction is crucial for accurate child type detection.

### Child Type Detection Logic

#### Fixed Algorithm (v1.2)
1. **Primary Check**: Any timetable entries → **School child**
2. **Fallback Logic**:
   - "fritids" time registrations → **School child**
   - "förskola" time registrations → **Preschool child** 
   - No clear indicators → **Preschool child** (default)

#### Previous Issue (FIXED)
- **Problem**: Used `has_school` property which included time registrations
- **Result**: Preschool children incorrectly classified as school children
- **Solution**: Now uses `has_timetable_entries` for accurate detection

## API Endpoints

### Timetable (School Lessons)
- **Primary**: `GET /timetable/timetable/gettimetablelist`
- **Fallback**: `POST /timetable/timetable/gettimetablelist`  
- **Data**: Subject schedules, teachers, rooms, times

### Time Registration (Preschool/Fritids)
- **Primary**: `GET /TimeRegistration/TimeRegistration/GetTimeRegistrations/`
- **Alternative**: `GET /TimeRegistration/TimeRegistration/GetCalendarData/`
- **Data**: Care schedules, attendance, leave days

### Communication
- **News**: `GET /news/news/getpupilnews`
- **Timeline**: `GET /timeline/timeline/getpupiltimeline`

## Sensor Types

### Per-Pupil Sensors
1. **Schedule Sensors**
   - `sensor.{name}_schedule` - Complete upcoming schedule
   - `sensor.{name}_today_schedule` - Today's activities
   - `binary_sensor.{name}_has_school_today` - School lessons today
   - `binary_sensor.{name}_has_preschool_today` - Care activities today
   - `sensor.{name}_child_type` - School vs preschool classification

2. **Communication Sensors**
   - `sensor.{name}_news` - School news count and content
   - `sensor.{name}_timeline` - Timeline entries count and content

### System Sensors
- `sensor.infomentor_pupil_count` - Total children in account

## Recent Major Fixes

### Authentication Form Submission Fix (v0.0.98) - 2025-12-09
- **Issue**: School selection page appearing when it shouldn't, causing wrong school routing
- **Symptom**: Users redirected to "Avesta kommun" or seeing school selection when manual login doesn't show it
- **Root Cause Discovery**: 
  - Manual browser login: submit username + password + **ALL 89 school fields** in one POST
  - Our code: only submitting username + password + viewstate fields
  - InfoMentor login form contains ALL school options as hidden fields (`login_ascx$IdpListRepeater$ctl##$url` and `$number`)
  - Browser submits everything; InfoMentor uses credentials to determine correct school
  - Our code wasn't submitting school fields, causing InfoMentor to show selection page or route incorrectly
- **Previous Misunderstanding**:
  - Thought we needed to "select" a school by navigating to its URL
  - Built complex scoring system to choose which school URL to visit
  - This was completely wrong - no navigation needed!
- **Correct Behaviour**:
  - Login form contains all 89 schools as hidden fields
  - Submit ALL fields (credentials + ALL school data) in ONE POST
  - InfoMentor determines school from username/password
  - No school selection page appears
  - No navigation to school-specific URLs needed
- **Fix**: 
  - Now extract and submit ALL hidden form fields, not just viewstate
  - Removed erroneous school selection navigation logic
  - Simplified flow to match real browser behaviour
  - School selection page should never appear now
- **Impact**: Authentication works exactly like manual browser login - clean, simple, reliable

### School Selection Scoring Overhaul (v0.0.97) - 2025-12-09
- **NOTE**: This entire approach was based on a misunderstanding. See v0.0.98 for correct fix.
- **What we thought**: Need to select one of 89 schools by navigating to its URL
- **Issue**: Stored school selection was repeatedly used even when it returned no pupils
- **Symptom**: User kept being directed to "Avesta kommun" instead of correct "Örkelljunga kommun"
- **Understanding**: 
  - InfoMentor presents ALL 89 schools in a single form (as hidden fields)
  - Authentication happens on infomentor.se domains for all users
  - Username email domain matching is NOT useful (e.g., "callycode.com" won't match any school)
  - Most schools use `sso.infomentor.se/login.ashx?idp=` URLs
  - Some use `ims-grandid-api.infomentor.se/Login/initial?communeId=` URLs  
  - Some are demo/test environments that should be avoided
- **Root Cause**: 
  - Stored school (#98 Avesta) returned with automatic selection (score 1000)
  - Scoring system favoured demo/test entries over real municipalities
  - "Övrigt InfoMentor Demo" entries scored higher than actual kommun entries
  - No mechanism to detect and clear failing school selections
- **Fix**: 
  - Stored school now gets +500 bonus (not automatic win)
  - Completely redesigned scoring heuristics:
    - Real "kommun" entries: +200 (highest priority for Swedish users)
    - Standard SSO URLs (`sso.infomentor.se/login.ashx?idp=`): +150
    - Demo/test entries: -100 to -300 (heavy penalties)
    - User type (elever/vårdnadshavare): +25 to +30
    - Removed username domain matching penalties (not applicable)
  - Automatic clearing of stored school when auth succeeds but returns no pupils
  - Next attempt uses scoring to find correct school
  - Added better logging to explain school selection reasoning
- **Example Scores** (without stored preference):
  - "Örkelljunga kommun": 200 (kommun) + 150 (sso URL) = 350
  - "Övrigt InfoMentor Demo Web": -100 (övrigt) - 200 (demo title) - 300 (demo URL) = -600
  - Real municipalities will now consistently score higher than demo/test entries
- **Additional Fix**: Time-based retry avoidance
  - Skip authentication during first 5 minutes of each hour (suspected maintenance window)
  - Uses cached data instead if available and less than 24 hours old
- **Impact**: Integration now correctly selects real kommun entries over demo/test sites, with automatic self-correction when wrong school is stored

### Schedule Freshness Gate (v1.6)
- **Issue**: Data freshness sensor (and retry cadence) treated partially updated payloads as fresh even when some pupils failed to return schedules.
- **Fix**: Added a dedicated completeness check that tracks per-pupil schedule status, only updating the freshness timestamp when every pupil has a fresh schedule.
- **Storage**: Introduced `last_complete_schedule_update` so cached data can report true freshness after restart without misusing the legacy timestamp.
- **Observability**: Sensors now expose which pupils are missing or cached, and the coordinator keeps retrying aggressively until the set is complete.
- **Impact**: Eliminates false "< 1 day" freshness claims, improves logging, and clarifies why data is still considered stale.

### School Selection Heuristic Upgrade (v1.5)
- **Issue**: Authentication frequently diverted to the first municipality IdP (for example Avesta) instead of the correct school, leading to repeated login failures
- **Fix**: Added weighted heuristics that reuse the cached IdP choice, boost InfoMentor-operated endpoints, and prefer options matching the user's e-mail domain while penalising unrelated entries
- **Impact**: Automatic school selection now locks onto the intended IdP, avoiding incorrect detours and reducing the need for manual retries

### Today Schedule Date Calculation Fix (v1.4) - 2025-10-20
- **Issue**: Today's schedule showing incorrect date (e.g., Saturday schedule on Monday)
- **Symptom**: "Tomorrow" schedule correct, but "Today" schedule stuck on old date
- **Root Cause**: 
  - `get_today_schedule()` returned a cached value (`pupil_data["today_schedule"]`) set during data fetch
  - When InfoMentor servers had issues for multiple days, stale cached value was preserved
  - `get_tomorrow_schedule()` always calculated date dynamically, so it worked correctly
- **Example Scenario**:
  - Saturday: Fresh data fetched, `today_schedule` cached as Saturday
  - Sunday-Monday: Server issues, stale cache preserved (including Saturday's `today_schedule`)
  - Monday: `get_today_schedule()` returned Saturday ❌, `get_tomorrow_schedule()` calculated Tuesday ✅
- **Fix**: Modified `get_today_schedule()` to calculate date dynamically like `get_tomorrow_schedule()`
  - Now searches schedule list for current date each time instead of using cached value
  - Ensures correct date even when schedule data is several days old
- **Impact**: Today's schedule always shows correct date, resilient to server outages

### Home Assistant Restart Resilience (v1.3)
- **Issue**: HA restarts were forcing immediate authentication attempts, causing "Authentication Expired" errors
- **Cause**: Integration attempted fresh data fetch on startup even when recent cached data was available
- **Additional Issue**: Cached data was loaded as dictionaries but sensors expected model objects with attributes
- **Server Reliability Issue**: InfoMentor servers sometimes authenticate successfully but fail to return pupil IDs
- **Fix**: 
  - Load cached data from storage immediately on restart if less than 72 hours old
  - Added deserialization function to convert cached dict data back to proper model objects (ScheduleDay, NewsItem, etc.)
  - Added serialization function to properly convert dataclass objects to JSON-compatible dicts when saving
  - Defer authentication checks to background tasks scheduled 30 seconds after startup
  - Periodic background auth verification every 12 hours (non-blocking)
  - Automatic retry with exponential backoff when authentication succeeds but pupil IDs aren't retrieved (up to 5 attempts)
  - Falls back to cached pupil IDs when InfoMentor servers fail to return them
  - Manual retry service for when automatic retries aren't enough
  - Authentication failures no longer block integration startup or data availability
- **Impact**: Integration remains functional through HA restarts and temporary authentication issues
- **Behaviour**: Uses cached data immediately, verifies credentials in background without disrupting service, automatically retries when InfoMentor servers are unreliable

### Child Type Detection Fix (v1.2)
- **Issue**: Preschool children showing as school children in HA
- **Cause**: Incorrect use of `has_school` property for classification
- **Fix**: Added `has_timetable_entries` property and updated logic
- **Impact**: Accurate school vs preschool distinction

### Timetable Endpoint Migration
- **Issue**: Calendar endpoint mixed holidays/events with lessons
- **Change**: Switched to dedicated timetable endpoint
- **Benefit**: More reliable school lesson detection

### Property Clarification
- **`has_school`**: Kept for backward compatibility (any activity)
- **`has_timetable_entries`**: New property for precise lesson detection
- **Clear semantics**: Each property has a specific, documented purpose

### Schedule Fetching Optimisation (v0.0.31)
- **Issue**: Monday cache issues when schedule data wasn't available for the current day
- **Solution**: Modified date range calculation to always fetch through end of following week
- **Implementation**: Calculate days to next Sunday (13 - current_weekday) for consistent coverage
- **Benefit**: Prevents cache gaps and ensures complete week coverage regardless of fetch day

## Testing Strategy

### Unit Tests
- **Logic Tests**: Child type detection algorithms
- **Model Tests**: Data structure validation
- **API Tests**: Endpoint parsing and error handling

### Integration Tests  
- **Live API Tests**: Real InfoMentor authentication and data retrieval
- **Schedule Tests**: Complete workflow validation
- **Edge Case Tests**: Holiday handling, missing data scenarios

### Validation Tests
- **Fix Validation**: Specific tests for recent fixes
- **Regression Tests**: Ensure fixes don't break existing functionality

## Configuration

### Required Settings
- **Username**: InfoMentor login credential
- **Password**: InfoMentor password
- **Auto-discovery**: Automatic pupil detection

### Advanced Settings
- **Update Interval**: Default 30 minutes
- **Debug Logging**: Detailed troubleshooting information
- **Fallback Handling**: Graceful degradation on API failures

## Security & Privacy

### Data Handling
- **Local Storage**: Credentials stored securely in HA
- **API Access**: Only data user has permission to view
- **No External Sharing**: Data stays within Home Assistant
- **Session Management**: Automatic re-authentication

### Compliance
- **Home Assistant Standards**: Follows HA security best practices
- **OAuth Support**: Uses InfoMentor's authentication flow
- **Error Logging**: Sensitive data excluded from logs

## Future Enhancements

### Planned Features
- **Assignment Tracking**: Homework and project monitoring
- **Attendance Records**: Absence and tardiness tracking  
- **Grade Information**: Academic progress (if API supports)
- **Push Notifications**: Real-time updates via HA notifications

### Technical Improvements
- **Async Performance**: Further optimisation of API calls
- **Caching Strategy**: Intelligent data caching for performance
- **Multi-language**: Support for other InfoMentor regions
- **Advanced Filtering**: Customisable data filtering options

## Known Limitations

### API Constraints
- **School Dependency**: Timetable availability varies by school
- **Data Timing**: Some data not available far in advance
- **Regional Variations**: Primarily tested with Swedish InfoMentor

### Integration Limits
- **Read-Only**: Cannot modify InfoMentor data from HA
- **Polling-Based**: No real-time push notifications from InfoMentor
- **Session Limits**: May need periodic re-authentication

## Support & Documentation

### User Resources
- **Setup Guide**: Step-by-step installation instructions
- **Troubleshooting**: Common issues and solutions
- **Example Automations**: Sample Home Assistant automations
- **Dashboard Cards**: UI examples and templates

### Developer Resources
- **API Documentation**: InfoMentor endpoint details
- **Testing Guide**: How to run and extend tests
- **Contributing**: Guidelines for code contributions
- **Architecture Notes**: Technical implementation details

## Version History

### v0.0.98 (Current)
- ✅ **MAJOR FIX**: Root cause identified for school selection issues
- ✅ Now submitting ALL form fields (including 89 school options) with credentials
- ✅ Removed erroneous school selection navigation logic
- ✅ Authentication now works like real browser - one POST with everything
- ✅ InfoMentor determines school from username/password, not from navigation
- ✅ Simplified flow - no more trying to "select" schools by clicking URLs

### v0.0.97
- ✅ Complete scoring overhaul based on actual InfoMentor form structure
- ✅ Real "kommun" entries now score +200 (highest priority)
- ✅ Demo/test entries heavily penalized (-100 to -300)
- ✅ Standard SSO URLs prioritized (+150)
- ✅ Removed username domain matching (not applicable to InfoMentor)
- ✅ Stored school preference: +500 bonus (allows override if wrong)
- ✅ Auto-clear stored school when it returns no pupils
- ✅ Time-based retry avoidance (skip first 5 minutes of each hour)
- ✅ Added `clear_selected_school()` method to storage
- ✅ Improved logging for school selection reasoning

### v1.4
- ✅ Fixed today's schedule date calculation (was showing stale cached dates)
- ✅ Made `get_today_schedule()` calculate date dynamically like `get_tomorrow_schedule()`
- ✅ Improved resilience when InfoMentor servers have multi-day outages

### v1.3
- ✅ Fixed HA restart authentication issues
- ✅ Implemented cached data loading on startup
- ✅ Added deserialization of cached data (dict → model objects)
- ✅ Added serialization when saving data (model objects → dict)
- ✅ Added background authentication verification (non-blocking)
- ✅ Automatic retry with exponential backoff for pupil ID retrieval (5 attempts, 3-15 seconds)
- ✅ Fallback to cached pupil IDs when InfoMentor servers fail
- ✅ Added manual authentication retry service for unreliable servers
- ✅ Improved resilience to temporary auth failures and server issues
- ✅ Integration remains functional with cached data during auth issues

### v1.2
- ✅ Fixed child type detection logic
- ✅ Added `has_timetable_entries` property
- ✅ Improved timetable endpoint usage
- ✅ Enhanced debugging and validation tools

### v1.1
- ✅ Timetable endpoint migration
- ✅ Improved error handling
- ✅ Better authentication flow

### v1.0
- ✅ Initial release
- ✅ Basic schedule and communication features
- ✅ Multi-pupil support

## 📁 Project Structure

```
im-tools/
├── custom_components/infomentor/     # Main integration code
│   ├── __init__.py                   # Integration setup
│   ├── config_flow.py               # Configuration flow
│   ├── sensor.py                    # Sensor entities
│   ├── infomentor/                  # Core library
│   │   ├── __init__.py
│   │   ├── auth.py                  # Authentication handling
│   │   ├── client.py                # API client
│   │   ├── models.py                # Data models
│   │   └── exceptions.py            # Custom exceptions
│   └── manifest.json                # Integration manifest
├── tests/                           # Test and debug scripts
│   ├── README.md                    # Testing documentation
│   ├── test_requirements.txt        # Test dependencies
│   ├── test_*.py                    # Main test scripts
│   ├── debug_*.py                   # Debug scripts
│   ├── trace_*.py                   # OAuth tracing scripts
│   ├── quick_*.py                   # Quick verification scripts
│   └── check_*.py                   # Error checking scripts
├── debug_output/                    # Test results and debug data (gitignored)
│   ├── *.html                       # HTML captures from tests
│   ├── *.json                       # API response data
│   └── *.log                        # Test execution logs
├── run_tests.py                     # Test runner script
├── README.md                        # Main documentation
├── requirements.txt                 # Integration dependencies
├── .env                            # Environment variables (gitignored)
├── env.example                     # Environment template
└── hacs.json                       # HACS configuration
```

## 🔧 Core Components

### Authentication System (`auth.py`)
- **OAuth Flow**: Complete two-stage OAuth implementation
- **Session Management**: Automatic session renewal and CSRF handling
- **Cookie Reuse**: Successful logins now persist the browser cookies in HA storage so restarts can resume the session without re-running OAuth.
- **Multi-Domain Support**: Handles both legacy and modern InfoMentor domains
- **Error Handling**: Robust authentication error detection and recovery

### API Client (`client.py`)
- **Modern JSON APIs**: Direct API communication (no HTML scraping)
- **Multi-Child Support**: Automatic pupil discovery and management
- **Data Retrieval**: Schedule, news, timeline, and calendar data
- **Rate Limiting**: Respectful API usage with configurable intervals

### Data Models (`models.py`)
- **Structured Data**: Type-safe data models for all InfoMentor entities
- **Schedule Parsing**: Complex timetable and time registration handling
- **News & Timeline**: Rich content models with metadata
- **Validation**: Input validation and data consistency checks

### Home Assistant Integration
- **Config Flow**: User-friendly setup with credential validation
- **Sensors**: Individual sensors per child with detailed attributes
- **Services**: Manual refresh and pupil switching capabilities
- **Stale Data Retries**: When data is older than 24 hours the coordinator retries roughly hourly with a randomised offset (to avoid :00 clashes) until fresh data is retrieved.
- **Error Handling**: Graceful degradation and user-friendly error messages

#### Services & Manual Actions
- **Targetable Actions**: All InfoMentor services expose HA's `target` selector so users can pick a specific InfoMentor device/account when running an action.
- **Backoff Awareness**: Manual refreshes now respect retry/backoff rules and return meaningful errors instead of silently doing nothing.
- **Diagnostics**: `debug_authentication` logs the detailed flow result, making it easy to attach output to GitHub issues.
- **Entity Cleanup**: `cleanup_duplicate_entities` supports scoped cleanups, dry-run reporting, and aggressive "wipe everything" mode without throwing exceptions.
- **Automation-Friendly**: Advanced users can pass `config_entry_id` in service data to scope an action directly from YAML.

## 🧪 Testing Infrastructure

### Test Categories
- **Authentication Tests**: OAuth flow validation and credential testing
- **API Tests**: Data retrieval and parsing verification
- **Debug Scripts**: Development and troubleshooting tools
- **Integration Tests**: End-to-end functionality verification

### Test Runner (`run_tests.py`)
- **Organised Execution**: Categorised test execution with progress tracking
- **Output Management**: Automatic log capture to `/debug_output/`
- **Error Reporting**: Detailed failure analysis and debugging information
- **CI/CD Ready**: Structured for automated testing environments

### Debug Output Management
- **Automatic Capture**: All test results saved to `/debug_output/`
- **Gitignored**: Debug data excluded from version control
- **Timestamped**: Organised by execution time for easy tracking
- **Multiple Formats**: HTML captures, JSON data, and execution logs

## 🚀 Development Workflow

### Local Development
1. **Setup**: Clone repository and install dependencies
2. **Environment**: Configure `.env` with InfoMentor credentials
3. **Testing**: Run `python run_tests.py` to verify functionality
4. **Development**: Modify code and re-test iteratively

### Testing Process
1. **Unit Tests**: Individual component testing
2. **Integration Tests**: Full OAuth and API flow testing
3. **Debug Scripts**: Troubleshooting specific issues
4. **Manual Verification**: Real-world usage testing

### Quality Assurance
- **Code Standards**: British English, tabs, ES modules where applicable
- **Error Handling**: Comprehensive error catching and logging
- **Documentation**: Inline comments and external documentation
- **Modularity**: Reusable functions and clean separation of concerns

## 📋 Current Status

### ✅ Completed Features
- Complete OAuth authentication flow
- Multi-child pupil discovery
- Schedule data retrieval (using correct timetable endpoint)
- News and timeline data retrieval
- Home Assistant sensor integration
- Comprehensive testing infrastructure
- Organised project structure

### 🔄 In Progress
- Schedule HTML parsing improvements
- Time registration data parsing
- Enhanced error handling and recovery
- Performance optimisation

### 📝 Future Enhancements
- Calendar event integration
- Push notification support
- Advanced automation examples
- Mobile app companion features

## 🛠️ Technical Decisions

### Architecture Choices
- **Modern APIs**: JSON-based communication over HTML scraping
- **Session-Based Auth**: Secure credential handling with automatic renewal
- **Modular Design**: Separated concerns for maintainability
- **Type Safety**: Structured data models for reliability

### API Endpoint Changes
- **Timetable Data**: Updated to use `/timetable/timetable/gettimetablelist` instead of calendar endpoint
- **Correct Data Source**: Now fetching school timetable entries from the proper endpoint
- **Schedule Logic**: `has_school` property now correctly indicates ANY structured activity (school/preschool/fritids)

### Development Principles
- **User Experience**: Simple setup and reliable operation
- **Maintainability**: Clean code with comprehensive documentation
- **Extensibility**: Modular design for future enhancements
- **Security**: Secure credential handling and data protection

---

*This outline reflects the current organised state of the project with proper separation of concerns and comprehensive testing infrastructure.* 
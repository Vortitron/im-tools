# InfoMentor Home Assistant Integration

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Vortitron&repository=im-tools&category=integration)

This custom component integrates InfoMentor school communication platform with Home Assistant, providing real-time access to school schedules, news, and timeline entries for your children.

## Features

### Core Functionality
- **Multiple Children Support**: Manage multiple pupils/children from one or more schools
- **Real-time Schedule Data**: Access current and upcoming school schedules
- **News & Timeline**: Get school news and timeline entries
- **Child Type Detection**: Automatically distinguish between school and preschool children
- **Robust Authentication**: Secure login with session management

### Sensors Created

For each pupil, the integration creates several sensors:

#### Schedule Sensors
- **Today Schedule**: Current day's schedule status (school/preschool_fritids/no_activities)
- **Schedule**: Complete upcoming schedule (7 days) with detailed breakdown
- **Has School Today**: Binary sensor indicating if child has school lessons today
- **Has Preschool Today**: Binary sensor for preschool/fritids activities today
- **Child Type**: Determines if child is "school" or "preschool" based on timetable data

#### Communication Sensors
- **News**: Count and details of unread school news
- **Timeline**: Count and details of timeline entries

#### System Sensors
- **Pupil Count**: Total number of children in the account

### Schedule Properties Clarification

The integration uses different properties to accurately represent activities:

- **`has_school`**: Any scheduled activity (timetable entries OR time registrations)
- **`has_timetable_entries`**: Only actual school lessons from the timetable
- **`has_preschool_or_fritids`**: Time registrations for preschool/after-school care

### Child Type Detection Logic

The integration correctly distinguishes between school and preschool children:

1. **Primary**: Children with timetable entries → **School child**
2. **Fallback**: Children with "fritids" time registrations → **School child** 
3. **Fallback**: Children with "förskola" time registrations → **Preschool child**
4. **Default**: No clear indicators → **Preschool child**

This ensures accurate classification even when timetable data is temporarily unavailable.

## Installation

### Option 1: HACS (Recommended)
1. Install HACS if you haven't already
2. Add this repository as a custom repository in HACS
3. Install "InfoMentor" from HACS
4. Restart Home Assistant

### Option 2: Manual Installation
1. Download the latest release
2. Copy the `custom_components/infomentor` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

### Initial Setup
1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration** 
3. Search for "InfoMentor"
4. Enter your InfoMentor credentials
5. The integration will discover all your children automatically

### Important Notes
- **Credentials**: Use the same username/password you use for the InfoMentor website
- **Multiple Children**: All children associated with your account are automatically added
- **Updates**: Schedule data updates every 30 minutes by default
- **Authentication**: Sessions are managed automatically with re-authentication as needed

## Usage Examples

### Automations
```yaml
# Notify when child has school today
- alias: "School Day Notification"
  trigger:
    - platform: state
      entity_id: binary_sensor.felix_has_school_today
      to: "on"
  action:
    - service: notify.mobile_app
      data:
        message: "Felix has school today!"

# Different actions for school vs preschool
- alias: "Morning Routine"
  trigger:
    - platform: time
      at: "07:00:00"
  condition:
    - condition: state
      entity_id: binary_sensor.felix_has_school_today
      state: "on"
  action:
    - choose:
        - conditions:
            - condition: state
              entity_id: sensor.felix_child_type
              state: "school"
          sequence:
            - service: tts.speak
              data:
                message: "Time to get ready for school!"
        - conditions:
            - condition: state
              entity_id: sensor.felix_child_type
              state: "preschool"
          sequence:
            - service: tts.speak
              data:
                message: "Time to get ready for preschool!"
```

### Dashboard Cards
```yaml
# Today's schedule overview
type: entities
title: Today's Schedule
entities:
  - sensor.felix_today_schedule
  - sensor.isolde_today_schedule
  - binary_sensor.felix_has_school_today
  - binary_sensor.isolde_has_preschool_today

# Weekly schedule
type: custom:auto-entities
card:
  type: entities
  title: This Week's Schedule
filter:
  include:
    - entity_id: "sensor.*_schedule"
      attributes:
        schedule_days: "*"
```

## Recent Improvements

### Child Type Detection Enhancement (v1.2)
- **Fixed Logic**: Corrected child type detection to properly distinguish school vs preschool children
- **Timetable Focus**: Now primarily uses actual timetable entries for school child detection
- **Better Properties**: Added `has_timetable_entries` property for clearer logic
- **Improved Fallback**: Enhanced fallback logic using time registration types

### Timetable Endpoint Migration
- **Better Data Source**: Switched from calendar endpoint to dedicated timetable endpoint
- **More Accurate**: School timetables now retrieved from proper `/timetable/timetable/gettimetablelist` endpoint
- **Reliable Classification**: Improved accuracy in distinguishing educational content from general calendar events

## Troubleshooting

### Common Issues

#### Child Appears as Wrong Type
- **Issue**: School child shows as preschool or vice versa
- **Solution**: Check the `sensor.child_name_child_type` attributes for detailed reasoning
- **Data**: The `description` attribute explains the classification logic used

#### No Schedule Data
- **Check Authentication**: Verify credentials in the integration configuration
- **Check Pupils**: Ensure pupil IDs are correctly retrieved
- **Check Logs**: Look for authentication or API errors in Home Assistant logs

#### Missing Timetable Entries
- **School System**: Some schools may not publish timetables through the API
- **Timing**: Timetables might not be available far in advance
- **Fallback**: The system uses time registration data as fallback for classification

### Debug Information

Enable debug logging to troubleshoot issues:

```yaml
logger:
  default: warning
  logs:
    custom_components.infomentor: debug
```

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add/update tests as needed
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial integration. InfoMentor is a trademark of its respective owners. This integration is not affiliated with or endorsed by InfoMentor.

## Recent Fixes

### Session Expiration & Authentication Retry (RESOLVED ✅)

**Problem**: The integration was experiencing "HandleUnauthorizedRequest" errors and HTTP 500 failures when accessing timetable and time registration APIs, preventing Felix's timetable entries from being retrieved.

**Root Cause**: InfoMentor sessions were expiring during API calls, but the integration had no automatic re-authentication mechanism, causing persistent failures.

**Final Fix Applied**:
1. **Credential Storage**: Modified auth handler to store username/password for re-authentication
2. **Session Monitoring**: Added detection of "HandleUnauthorizedRequest" in API responses
3. **Automatic Retry**: Implemented `_handle_authentication_failure()` method for automatic re-authentication
4. **Retry Logic**: Added retry mechanisms to both timetable and time registration endpoints
5. **Smart Retries**: Limited to one retry per request to prevent infinite loops

**Verification**: The integration now automatically re-authenticates when sessions expire, eliminating persistent authentication failures.

### Timetable Display Bug (RESOLVED ✅)

**Problem**: Felix was correctly identified as a school child, but his timetable entries were not appearing in his schedule attributes - only fritids time registrations were visible.

**Root Cause**: The sensor code was trying to access `entry.classroom` but the `TimetableEntry` model uses `entry.room`. This caused an `AttributeError` that silently prevented timetable entries from being included in the schedule display.

**Final Fix Applied**:
1. **Corrected Field Name**: Changed `entry.classroom` to `entry.room` in both schedule sensors  
2. **Added Null Safety**: Added null checks for `start_time` and `end_time` in display logic
3. **Fixed Time Comparison**: Fixed `earliest_start` and `latest_end` properties to filter out `None` values

**Verification**: Testing confirms that timetable entries now properly appear in schedule attributes alongside time registrations.

### Child Type Detection Enhancement (RESOLVED ✅)

**Problem**: School children were appearing as preschool children because the classification logic was flawed.

**Root Cause**: The `has_school` property included both timetable entries and time registrations, making preschool children appear as school children.

**Final Fix Applied**:
1. **New Property**: Added `has_timetable_entries` property for precise school lesson detection
2. **Improved Logic**: Child type sensor now uses `has_timetable_entries` for primary classification
3. **Better Properties**: Clarified semantics of `has_school` vs `has_timetable_entries` vs `has_preschool_or_fritids`
4. **Enhanced Fallback**: Added fallback logic using time registration types

**Verification**: Testing confirms accurate school vs preschool distinction.

### Pupil Switching Issue (RESOLVED ✅)

**Problem**: Both pupils were showing identical schedule data because the pupil switching mechanism wasn't working correctly.

**Root Cause**: The pupil switching was incorrectly treating the server's `302 Found` redirect response as a failure, when it's actually the correct response for a successful pupil switch.

**Final Fix Applied**:
1. **Correct HTTP Status Handling**: Modified `switch_pupil()` to accept both `200 OK` and `302 Found` as successful responses
2. **Proper Redirect Handling**: Added `allow_redirects=True` to handle server-side redirects correctly
3. **Increased Switch Delay**: Extended delay to 2.0 seconds to ensure server-side session changes take effect
4. **Endpoint Prioritisation**: Prioritised the hub endpoint (`hub.infomentor.se`) as the primary switching endpoint

**Verification**: Testing confirms that Felix and Isolde now return different data:
- Felix: 12:00-16:00 time registration, 35 timetable entries across various date ranges
- Isolde: 08:00-16:00 time registration, different schedule pattern

## Troubleshooting

### Both pupils showing the same schedule
This issue has been fixed in the latest version. If you still experience it:
1. Check the logs for switch ID mapping (should show different switch IDs for each pupil)
2. Ensure the integration has been restarted after the update
3. Look for debug messages showing successful pupil switching

### Authentication failures
- Verify your credentials are correct
- Check if you can log in to InfoMentor directly
- Look for OAuth-related errors in the logs

## Debug Logging

To enable debug logging, add this to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.infomentor: debug
```

## Support

For issues and feature requests, please check the logs first and include relevant debug information when reporting problems. 
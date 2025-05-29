# InfoMentor Home Assistant Integration

A Home Assistant custom component for integrating with InfoMentor school system.

**Author**: [Vortitron](https://github.com/Vortitron)

## ✅ Status: COMPLETED

The InfoMentor integration is now **fully functional** with complete API parsing capabilities.

## Features

### ✅ Implemented
- **Authentication**: Multi-pupil authentication with InfoMentor
- **Calendar Data**: Parse school events, holidays, and announcements
- **Time Registration**: Parse fritids/preschool schedules with detailed timing
- **Combined Schedules**: Daily schedules combining timetable and time registration data
- **Real-time Data**: Direct API integration (no HTML scraping needed)
- **Multiple Pupils**: Support for families with multiple children

### 📊 Data Types Supported
- **Calendar Entries**: School events, holidays, announcements
- **Time Registrations**: Fritids schedules with start/end times, status, lock information
- **Schedule Days**: Combined daily view with both timetable and time registration
- **News Items**: School news and announcements
- **Timeline Entries**: Activity timeline

## API Endpoints Discovered

InfoMentor uses a modern SPA architecture with JSON APIs:

### Calendar API
- **Endpoint**: `/calendarv2/calendarv2/getentries`
- **Data**: School events, holidays, announcements
- **Format**: JSON array with detailed event information

### Time Registration API
- **Endpoint**: `/TimeRegistration/TimeRegistration/GetTimeRegistrations/`
- **Data**: Fritids/preschool schedules
- **Format**: JSON with `days` array containing detailed schedule information

### Configuration APIs
- **Calendar Config**: `/calendarv2/calendarv2/appData`
- **Time Registration Config**: `/timeregistration/timeregistration/appData`

## Installation

1. Copy the `custom_components/infomentor` directory to your Home Assistant `custom_components` folder
2. Restart Home Assistant
3. Add the integration through the UI or configuration.yaml

## Configuration

```yaml
# Example configuration.yaml
infomentor:
  username: your_username
  password: your_password
```

## Testing

The integration includes comprehensive test scripts:

```bash
# Test complete API integration
python3 test_infomentor_complete.py

# Test individual parsing methods
python3 test_api_parsing.py

# Debug and capture data
python3 debug_html_capture.py
```

## Development

### Project Structure
```
custom_components/infomentor/
├── infomentor/
│   ├── __init__.py
│   ├── auth.py          # Authentication handling
│   ├── client.py        # Main API client with parsing
│   ├── models.py        # Data models
│   └── exceptions.py    # Custom exceptions
├── __init__.py
├── config_flow.py
├── const.py
└── sensor.py
```

### Key Components

- **`InfoMentorAuth`**: Handles authentication and session management
- **`InfoMentorClient`**: Main API client with parsing methods
- **Data Models**: `TimetableEntry`, `TimeRegistrationEntry`, `ScheduleDay`
- **Parsing Methods**: Handle real InfoMentor JSON API responses

## Real Data Examples

### Calendar Entry (Holiday)
```json
{
  "id": 168144903,
  "title": "Kristi himmelfärdsdag (röd dag)",
  "startDate": "2025-05-29",
  "isAllDayEvent": true,
  "calendarEntryTypeId": 13
}
```

### Time Registration (Fritids Schedule)
```json
{
  "timeRegistrationId": 145045399,
  "date": "2025-05-26T00:00:00",
  "startDateTime": "2025-05-26T12:00:00",
  "endDateTime": "2025-05-26T16:00:00",
  "isLocked": false,
  "isSchoolClosed": false
}
```

## Technical Notes

- **No HTML Parsing**: InfoMentor uses modern JSON APIs
- **Authentication**: Session-based with CSRF protection
- **Multi-Pupil**: Supports switching between multiple children
- **Error Handling**: Comprehensive error handling and logging
- **Date Parsing**: Handles various InfoMentor date/time formats

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This integration is not officially affiliated with InfoMentor. Use at your own risk and ensure compliance with your school's data usage policies. 
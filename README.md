# InfoMentor Home Assistant Integration

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Vortitron&repository=im-tools&category=integration)

A custom Home Assistant integration for InfoMentor, providing access to pupil information, schedules, news, and timeline data.

## Features

- **Pupil Management**: Automatically detects and manages multiple pupils
- **Schedule Information**: Tracks school timetables and preschool/fritids time registrations
- **News & Timeline**: Access to school news and timeline entries
- **Smart Detection**: Distinguishes between school children and preschool children
- **Holiday Awareness**: Properly handles Swedish holidays and school closures

## Recent Improvements (v2.0)

### Fixed Pupil Detection Issues
- ✅ **Zero pupil count fixed**: Now correctly extracts pupil IDs from JSON structures
- ✅ **Duplicate filtering**: Eliminates duplicate pupils with different IDs
- ✅ **Parent account filtering**: Excludes parent accounts from pupil list
- ✅ **Improved name extraction**: Better parsing of pupil names from hub pages

### Enhanced Schedule Accuracy
- ✅ **Holiday detection**: Properly identifies and excludes Swedish holidays ("Lovdag", "röd dag", etc.)
- ✅ **Time registration logic**: Correctly handles locked/empty registrations
- ✅ **School vs Preschool**: Accurate detection of school days vs preschool/fritids days
- ✅ **Data validation**: Improved parsing of timetable and time registration data

### Better Error Handling
- ✅ **Robust authentication**: Improved OAuth flow handling
- ✅ **Data validation**: Better filtering of invalid names and content
- ✅ **Logging improvements**: More detailed debug information

## Installation

1. Copy the `custom_components/infomentor` directory to your Home Assistant `custom_components` folder
2. Restart Home Assistant
3. Add the integration through the UI: Configuration → Integrations → Add Integration → InfoMentor

## Configuration

The integration requires your InfoMentor credentials:
- **Username**: Your InfoMentor username/email
- **Password**: Your InfoMentor password

## Sensors

The integration creates the following sensors for each pupil:

### General Sensors
- `sensor.infomentor_pupil_count` - Total number of pupils
- `sensor.{pupil_name}_news` - News items count
- `sensor.{pupil_name}_timeline` - Timeline entries count

### Schedule Sensors
- `sensor.{pupil_name}_schedule` - Complete schedule information
- `sensor.{pupil_name}_today_schedule` - Today's schedule details
- `binary_sensor.{pupil_name}_has_school_today` - Whether pupil has school today
- `binary_sensor.{pupil_name}_has_preschool_today` - Whether pupil has preschool/fritids today
- `sensor.{pupil_name}_child_type` - Determines if child is school-age or preschool

## Testing

The integration includes comprehensive tests:

```bash
# Run all tests
python run_tests.py

# Test specific functionality
python tests/test_improved_parsing.py
python tests/test_schedule_accuracy.py
```

## Troubleshooting

### Common Issues

1. **Zero pupils found**: 
   - Check credentials are correct
   - Verify you have access to pupil information in InfoMentor web interface

2. **Incorrect schedule data**:
   - The integration now properly handles Swedish holidays
   - Locked time registrations without times are not counted as activities

3. **Authentication issues**:
   - The integration uses OAuth flow - ensure your account supports this
   - Check Home Assistant logs for detailed error messages

### Debug Information

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.infomentor: debug
```

## Swedish Holiday Support

The integration recognises common Swedish holidays and school terms:
- Kristi himmelfärdsdag (Ascension Day)
- Nationaldagen (National Day)
- Lovdag (Holiday/School break)
- Röd dag (Public holiday)

## Data Privacy

This integration:
- Stores credentials securely in Home Assistant
- Only accesses data you have permission to view in InfoMentor
- Does not share data with third parties
- Follows Home Assistant security best practices

## Support

For issues and feature requests, please check the project repository.

## License

This project is licensed under the MIT License.

---

**Made with ❤️ for families using InfoMentor**

*If this integration helps you stay connected with your children's school life, consider starring the repository!* 
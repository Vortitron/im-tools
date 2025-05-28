# InfoMentor Home Assistant Integration

A modern Home Assistant integration for InfoMentor (Swedish school pupil management system), providing real-time access to news, timeline updates, and pupil information.

## Features

- 🔐 **Secure Authentication** - OAuth-based login with proper session management
- 👥 **Multi-Pupil Support** - Handle multiple children/pupils in one account
- 📰 **News Monitoring** - Track new announcements and communications
- 📅 **Timeline Updates** - Monitor assignments, events, and activities
- 🏠 **Home Assistant Native** - Full integration with HA ecosystem
- 🔄 **Automatic Updates** - Configurable polling intervals
- 🛠️ **Services** - Manual refresh and pupil switching capabilities

## Installation

### HACS (Recommended)

1. Add this repository to HACS as a custom repository
2. Install "InfoMentor" from HACS
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

### Manual Installation

1. Copy the `custom_components/infomentor` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Add the integration via Settings → Devices & Services

## Configuration

1. Go to Settings → Devices & Services
2. Click "Add Integration"
3. Search for "InfoMentor"
4. Enter your InfoMentor username/email and password
5. The integration will automatically discover all pupils associated with your account

## Entities

The integration creates the following entities for each configured account:

### Sensors

- **Pupil Count** - Total number of pupils in the account
- **News (per pupil)** - Number of news items with latest news details
- **Timeline (per pupil)** - Number of timeline entries with latest entry details

### Attributes

Each sensor provides rich attributes including:
- Pupil information (ID, name)
- Latest item details (title, content, author, date)
- Historical data (recent items list)

## Services

### `infomentor.refresh_data`

Manually refresh data for a specific pupil or all pupils.

```yaml
service: infomentor.refresh_data
data:
  pupil_id: "12345"  # Optional - if omitted, refreshes all pupils
```

### `infomentor.switch_pupil`

Switch the active pupil context for subsequent API calls.

```yaml
service: infomentor.switch_pupil
data:
  pupil_id: "12345"
```

## Automation Examples

### New News Notification

```yaml
automation:
  - alias: "InfoMentor New News Alert"
    trigger:
      - platform: state
        entity_id: sensor.pupil_12345_news
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state | int > trigger.from_state.state | int }}"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "New InfoMentor News"
          message: "{{ state_attr('sensor.pupil_12345_news', 'latest_title') }}"
```

### Daily Summary

```yaml
automation:
  - alias: "InfoMentor Daily Summary"
    trigger:
      - platform: time
        at: "18:00:00"
    action:
      - service: notify.family_group
        data:
          title: "Daily School Summary"
          message: >
            News: {{ states('sensor.pupil_12345_news') }} items
            Timeline: {{ states('sensor.pupil_12345_timeline') }} entries
```

## Troubleshooting

### Authentication Issues

- Verify your InfoMentor credentials are correct
- Check that your account has access to the pupils you're trying to monitor
- Ensure your internet connection is stable

### Data Not Updating

- Check the integration logs in Home Assistant
- Try manually refreshing using the `infomentor.refresh_data` service
- Verify the InfoMentor service is operational

### Multiple Pupils

- The integration automatically discovers all pupils associated with your account
- Each pupil gets separate sensors for news and timeline
- Use the pupil ID in service calls to target specific pupils

## Privacy & Security

- Credentials are stored securely in Home Assistant's encrypted storage
- All communication uses HTTPS with proper certificate validation
- Session cookies are managed automatically and securely
- No data is shared with third parties

## Support

For issues and feature requests, please use the GitHub repository issue tracker.

## Credits

Based on the original `im-tools` shell scripts, modernised for Home Assistant integration. 
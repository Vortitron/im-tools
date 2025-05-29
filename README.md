# InfoMentor Home Assistant Integration

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Vortitron&repository=im-tools&category=integration)

An **unofficial** Home Assistant integration for the InfoMentor school system, providing real-time access to your children's school information.

**Author**: [Vortitron](https://github.com/Vortitron)

## 🎯 What This Integration Does

InfoMentor is a popular school management system used in Sweden and other countries. This integration brings your children's school information directly into Home Assistant, allowing you to:

- **📅 Monitor School Schedules**: View daily timetables and fritids (after-school care) schedules
- **📢 Get School News**: Stay updated with announcements and important messages
- **🗓️ Track Events**: Monitor holidays, school events, and special activities
- **👥 Multi-Child Support**: Handle multiple children from the same InfoMentor account
- **🏠 Smart Home Integration**: Create automations based on school schedules

## ✅ Current Status: **FULLY FUNCTIONAL**

This integration is complete and ready for daily use with comprehensive API parsing capabilities.

## 🚀 Quick Start

### Prerequisites

- Home Assistant 2023.1 or newer
- InfoMentor account (provided by your school)
- HACS (Home Assistant Community Store) installed

### Installation Methods

#### Option 1: HACS Installation (Recommended)

1. **Add Repository to HACS**:
   - Open HACS in your Home Assistant
   - Go to "Integrations"
   - Click the three dots (⋮) in the top right
   - Select "Custom repositories"
   - Add this repository: `https://github.com/Vortitron/im-tools`
   - Select "Integration" as the category
   - Click "Add"

2. **Install the Integration**:
   - Search for "InfoMentor" in HACS
   - Click "Install"
   - Restart Home Assistant

3. **Add the Integration**:
   [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=infomentor)

#### Option 2: Manual Installation

1. **Download**: Download the `custom_components/infomentor` folder from this repository
2. **Copy**: Place it in your Home Assistant `config/custom_components/` directory
3. **Restart**: Restart Home Assistant
4. **Configure**: Go to Settings → Devices & Services → Add Integration → Search for "InfoMentor"

## 🔧 Configuration

### Basic Setup

1. **Add Integration**: Go to Settings → Devices & Services → Add Integration
2. **Search**: Type "InfoMentor" and select it
3. **Enter Credentials**: 
   - **Username**: Your InfoMentor username
   - **Password**: Your InfoMentor password
4. **Complete**: The integration will automatically discover all children linked to your account

### What Gets Created

After setup, you'll get sensors for each child:

- **`sensor.infomentor_[child_name]_news_count`**: Number of unread news items
- **`sensor.infomentor_[child_name]_timeline_count`**: Number of recent timeline entries  
- **`sensor.infomentor_[child_name]_today_schedule`**: Today's schedule details
- **`sensor.infomentor_[child_name]_latest_news`**: Most recent news item

## 📊 Available Data

### 📅 Schedule Information
- **Daily Timetables**: Regular school subjects with times
- **Fritids/After-care**: Before and after school care schedules
- **Combined View**: Full day overview with all activities
- **Status Info**: Whether schedules are locked or school is closed

### 📢 Communications
- **News Items**: School announcements and messages
- **Timeline Entries**: Activity updates and notifications
- **Event Calendar**: Holidays, special events, and important dates

### 👥 Multi-Child Support
- Automatic detection of all children on your account
- Individual sensors for each child
- Easy switching between children for detailed views

## 🏠 Smart Home Examples

### Automation Examples

**Morning School Reminder**:
```yaml
automation:
  - alias: "School Day Morning Reminder"
    trigger:
      platform: time
      at: "07:00:00"
    condition:
      condition: template
      value_template: "{{ states('sensor.infomentor_emma_today_schedule') != 'No school today' }}"
    action:
      service: notify.mobile_app
      data:
        message: "Emma has school today! Check her schedule."
```

**New School News Alert**:
```yaml
automation:
  - alias: "New School News"
    trigger:
      platform: state
      entity_id: sensor.infomentor_emma_latest_news
    action:
      service: notify.family
      data:
        title: "New School News"
        message: "{{ states('sensor.infomentor_emma_latest_news') }}"
```

### Dashboard Card Example

```yaml
type: entities
title: "Emma's School Info"
entities:
  - sensor.infomentor_emma_today_schedule
  - sensor.infomentor_emma_news_count
  - sensor.infomentor_emma_latest_news
  - sensor.infomentor_emma_timeline_count
```

## 🛠️ Advanced Features

### Services

The integration provides services for advanced control:

- **`infomentor.refresh_data`**: Manually refresh data for all or specific children
- **`infomentor.switch_pupil`**: Switch to view a different child's data

### Attributes

Each sensor includes detailed attributes with structured data:

```yaml
# Example: sensor.infomentor_emma_today_schedule attributes
start_time: "08:00"
end_time: "15:30" 
subjects: [...]
fritids_start: "12:00"
fritids_end: "16:00"
is_locked: false
```

## 🔍 Troubleshooting

### Common Issues

**"Invalid credentials" error**:
- Verify your InfoMentor username and password
- Check if your account requires 2FA (currently not supported)
- Ensure your account has access to pupil information

**"Cannot connect" error**:
- Check your internet connection
- Verify InfoMentor service is online
- Check Home Assistant logs for detailed error messages

**No data appearing**:
- Wait a few minutes for initial data sync
- Check if your children have upcoming schedules
- Verify permissions on your InfoMentor account

### Debug Mode

Enable debug logging to troubleshoot issues:

```yaml
logger:
  default: warning
  logs:
    custom_components.infomentor: debug
```

## 🤝 Contributing

Found a bug or want to contribute? 

- **Issues**: [Report bugs or request features](https://github.com/Vortitron/im-tools/issues)
- **Pull Requests**: Contributions are welcome!
- **Discussions**: Share your automations and use cases

## 📋 Technical Details

### Architecture
- **Modern API Integration**: Uses InfoMentor's JSON APIs (no HTML scraping)
- **Real-time Data**: Direct API communication for current information
- **Efficient Updates**: Smart polling with configurable intervals
- **Error Handling**: Robust error handling with detailed logging

### Data Sources
- **Calendar API**: `/calendarv2/calendarv2/getentries`
- **Time Registration API**: `/TimeRegistration/TimeRegistration/GetTimeRegistrations/`
- **Configuration APIs**: Various app configuration endpoints

### Security
- Credentials stored securely in Home Assistant's configuration
- Session-based authentication with automatic renewal
- CSRF protection handling

## ⚖️ Legal & Privacy

**Important**: This is an **unofficial** integration not affiliated with InfoMentor AB.

- ✅ **Use at your own risk**
- ✅ **Ensure compliance** with your school's data usage policies  
- ✅ **Respect rate limits** - the integration polls responsibly
- ✅ **Secure your Home Assistant** instance as it will contain your children's school data

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Made with ❤️ for families using InfoMentor**

*If this integration helps you stay connected with your children's school life, consider starring the repository!* 
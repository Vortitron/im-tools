# InfoMentor Home Assistant Integration - Project Outline

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
- **Error Handling**: Graceful degradation and user-friendly error messages

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
- Schedule data retrieval (basic structure)
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

### Development Principles
- **User Experience**: Simple setup and reliable operation
- **Maintainability**: Clean code with comprehensive documentation
- **Extensibility**: Modular design for future enhancements
- **Security**: Secure credential handling and data protection

---

*This outline reflects the current organised state of the project with proper separation of concerns and comprehensive testing infrastructure.* 
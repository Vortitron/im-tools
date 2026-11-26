# Tests

These run offline against mocked InfoMentor responses, and are what CI runs:

```bash
pip install pytest pytest-homeassistant-custom-component beautifulsoup4
pytest tests/test_school_data.py tests/test_check_in_out.py   # library and parsing
pytest tests/ha                                               # Home Assistant integration
```

`pytest-homeassistant-custom-component` pins a Home Assistant version, which needs a matching Python (CI uses 3.13).

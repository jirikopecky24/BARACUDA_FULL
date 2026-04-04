def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "ui: optional widget-level UI tests (run only in environments with PyQt6).",
    )

import sys
from pathlib import Path
import pytest

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import format_timestamp, APP_VERSION, I18N

def test_format_timestamp():
    test_cases = [
        (0.0, "00:00:00,000"),
        (3661.5, "01:01:01,500"),
        (59.999, "00:00:59,999"),
        (7322.004, "02:02:02,004"),
    ]
    for seconds, expected in test_cases:
        assert format_timestamp(seconds) == expected

def test_version_consistency():
    # Verify APP_VERSION is "1.0.0"
    assert APP_VERSION == "1.0.0"
    
    # Verify I18N titles contain APP_VERSION
    assert f"v{APP_VERSION}" in I18N["ja"]["title"]
    assert f"v{APP_VERSION}" in I18N["en"]["title"]
    
    # Verify 4 README files contain badge with version
    project_root = Path(__file__).parent.parent
    readme_files = ["README.md", "README_JA.md", "README_ZH.md", "README_KO.md"]
    expected_badge = f"Version-v{APP_VERSION}-"
    
    for readme in readme_files:
        readme_path = project_root / readme
        assert readme_path.exists(), f"{readme} does not exist"
        content = readme_path.read_text(encoding="utf-8")
        assert expected_badge in content, f"{readme} does not contain version badge {expected_badge}"

def test_no_hardcoded_transcribe_language():
    project_root = Path(__file__).parent.parent
    app_py_path = project_root / "src" / "app.py"
    
    assert app_py_path.exists()
    content = app_py_path.read_text(encoding="utf-8")
    
    assert 'language="ja"' not in content, "Should not contain language=\"ja\""
    assert 'language=None' in content, "Should contain language=None"

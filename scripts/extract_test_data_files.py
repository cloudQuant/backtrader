#!/usr/bin/env python3
"""Extract data file usage from each test file in the slow list."""
import re
import sys
from pathlib import Path

# regex to find data file references
DATA_FILE_RE = re.compile(r"['\"]([\w\u4e00-\u9fa5]+\.(?:csv|txt|json|parquet))['\"]", re.IGNORECASE)

def find_data_files(test_path: Path) -> list[str]:
    """Find data filenames referenced in a test file."""
    if not test_path.exists():
        return ["FILE_NOT_FOUND"]
    try:
        content = test_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return [f"READ_ERROR:{e}"]
    matches = DATA_FILE_RE.findall(content)
    # Filter to only data-like files (CSV/txt mostly)
    data_files = []
    for m in matches:
        if m.lower().endswith(('.csv', '.txt', '.parquet')):
            if m not in data_files:
                data_files.append(m)
    return data_files or ["(no data file detected)"]


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    for line in sys.stdin:
        path = line.strip()
        if not path:
            continue
        files = find_data_files(repo_root / path)
        print(f"{path}\t{','.join(files)}")

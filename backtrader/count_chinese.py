import os
import re
import subprocess

# Get all files with Chinese characters
result = subprocess.run(['grep', '-r', '-l', '[\u4e00-\u9fff]', '--include=*.py', '.'], 
                      capture_output=True, text=True, cwd=os.getcwd())
files_with_chinese = result.stdout.strip().split('\n') if result.stdout.strip() else []

# Count Chinese characters in each file
chinese_counts = []
for file_path in files_with_chinese:
    if file_path:  # Skip empty lines
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Find all Chinese characters
                chinese_chars = re.findall(r'[\u4e00-\u9fff]', content)
                count = len(chinese_chars)
                chinese_counts.append((count, file_path))
        except Exception as e:
            pass

# Sort by count descending
chinese_counts.sort(reverse=True)

# Output results
print(f'Total files with Chinese characters: {len(chinese_counts)}')
print('=' * 80)
print('Files with Chinese characters (sorted by count):')
print('=' * 80)
for count, file_path in chinese_counts:
    print(f'{count:4d} {file_path}')

#!/usr/bin/env python3
import os
import re

# Find all indicator files
indicators_dir = "/home/yun/Documents/backtrader/backtrader/indicators"
fixed_count = 0

for filename in os.listdir(indicators_dir):
    if filename.endswith('.py') and filename not in ['__init__.py', 'mabase.py']:
        filepath = os.path.join(indicators_dir, filename)
        
        with open(filepath, 'r') as f:
            content = f.read()
        
        # Pattern to match: def __init__(self): without *args, **kwargs
        # We'll replace it with: def __init__(self, *args, **kwargs):
        pattern = r'(\s+def __init__\(self)\):'
        replacement = r'\1, *args, **kwargs):'
        
        new_content = re.sub(pattern, replacement, content)
        
        # Also fix super().__init__() calls to pass args
        pattern2 = r'super\(([^,]+), self\).__init__\(\)'
        replacement2 = r'super(\1, self).__init__(*args, **kwargs)'
        new_content = re.sub(pattern2, replacement2, new_content)
        
        if new_content != content:
            with open(filepath, 'w') as f:
                f.write(new_content)
            print(f"Fixed: {filename}")
            fixed_count += 1

print(f"\nTotal files fixed: {fixed_count}")

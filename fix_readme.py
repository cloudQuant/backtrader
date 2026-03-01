#!/usr/bin/env python3
"""Fix remaining README.md formatting issues."""

import re

def fix_readme():
    with open('README.md', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    result = []
    in_table = False
    prev_was_table_row = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Detect table rows
        is_table_row = stripped.startswith('|') and '|' in stripped[1:]
        
        # Skip blank lines between table rows
        if in_table and not stripped and prev_was_table_row:
            if i + 1 < len(lines) and lines[i + 1].strip().startswith('|'):
                continue  # Skip this blank line
            else:
                in_table = False  # End of table
        
        # Track table state
        if is_table_row:
            in_table = True
            prev_was_table_row = True
        elif stripped:
            prev_was_table_row = False
            if not is_table_row:
                in_table = False
        
        result.append(line)
    
    content = ''.join(result)
    
    # Fix extra spaces around bold: ** text ** → **text**
    content = re.sub(r'\*\* ([^*]+) \*\*', r'**\1**', content)
    
    # Fix code block closing tags
    content = re.sub(r'^```bash\s*$', r'```', content, flags=re.MULTILINE)
    content = re.sub(r'^```python\s*$', r'```', content, flags=re.MULTILINE)
    content = re.sub(r'^```text\s*$', r'```', content, flags=re.MULTILINE)
    
    with open('README.md', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Fixed README.md formatting")

if __name__ == '__main__':
    fix_readme()

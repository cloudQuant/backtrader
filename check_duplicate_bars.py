#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check if any dates are processed multiple times as separate bars"""

import re
from collections import Counter

remove_log = 'logs/test_02_multi_extend_data_remove-metaprogramming_20251107_103630.log'

def count_next_calls_per_date(log_file):
    """Count how many times next() is implicitly called for each date"""
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Track dates in sequence
    dates_sequence = []
    for line in lines:
        # Look for date at start of line (indicating a new bar/next call)
        match = re.match(r'^(\d{4}-\d{2}-\d{2}T00:00:00)', line)
        if match:
            dates_sequence.append(match.group(1))
    
    # Count consecutive same dates (which shouldn't happen - each bar should be a different date)
    consecutive_same = []
    for i in range(1, len(dates_sequence)):
        if dates_sequence[i] == dates_sequence[i-1]:
            consecutive_same.append((i, dates_sequence[i]))
    
    return dates_sequence, consecutive_same

dates_seq, consec = count_next_calls_per_date(remove_log)

print(f"Total date entries in log: {len(dates_seq)}")
print(f"Consecutive same date entries: {len(consec)}")

if consec:
    print("\nFirst 20 consecutive same date entries:")
    for i, (line_num, date) in enumerate(consec[:20]):
        print(f"  Line {line_num}: {date}")

# Count unique dates in sequence
from collections import OrderedDict
unique_dates = list(OrderedDict.fromkeys(dates_seq))
print(f"\nUnique dates in sequence: {len(unique_dates)}")

# Now let's see what the bar_num progression looks like
# by analyzing dates that appear at month-end boundaries
print("\n" + "=" * 80)
print("ANALYZING MONTH TRANSITIONS")
print("=" * 80)

month_transitions = []
prev_month = None
for date in unique_dates:
    month = date[:7]  # YYYY-MM
    if prev_month and month != prev_month:
        month_transitions.append((prev_month, month))
    prev_month = month

print(f"\nMonth transitions found: {len(month_transitions)}")
print("\nFirst 20 month transitions:")
for i, (prev, curr) in enumerate(month_transitions[:20]):
    print(f"  {i+1:2d}. {prev} -> {curr}")


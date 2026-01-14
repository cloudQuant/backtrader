"""Sphinx configuration for Chinese documentation.

This is a separate configuration file for building Chinese documentation.
It imports the main conf.py and overrides language-specific settings.
"""

# Import all settings from main conf.py
import os
import sys

# Add the source directory to path
sys.path.insert(0, os.path.dirname(__file__))

from conf import *  # noqa: F401, F403

# Override language settings for Chinese
language = 'zh_CN'
html_title = f'{project} 中文文档'

# Use Chinese index
master_doc = 'index_zh'
root_doc = 'index_zh'

# Update announcement for language switcher
html_theme_options['announcement'] = '''
    <a href="https://backtrader.readthedocs.io/en/latest/" style="color: inherit;">English</a> |
    <strong style="color: #2962FF;">中文</strong>
'''

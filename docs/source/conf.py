"""Sphinx configuration for Backtrader documentation.

This configuration supports multi-language documentation (Chinese and English)
with automatic API documentation generation from source code docstrings.
"""
import os
import sys
from datetime import datetime

# Add project root to path for autodoc
sys.path.insert(0, os.path.abspath('../..'))

# -- Project information -----------------------------------------------------
project = 'Backtrader'
copyright = f'{datetime.now().year}, Backtrader Contributors'
author = 'Backtrader Contributors'

# Version info - read from package
try:
    from backtrader.version import __version__
    version = __version__
    release = __version__
except ImportError:
    version = '0.1'
    release = '0.1'

# -- General configuration ---------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',           # Auto-generate docs from docstrings
    'sphinx.ext.autosummary',       # Generate summary tables
    'sphinx.ext.viewcode',          # Add links to source code
    'sphinx.ext.napoleon',          # Support Google/NumPy docstrings
    'sphinx.ext.intersphinx',       # Link to other project docs
    'sphinx.ext.todo',              # Support TODO items
    'sphinx.ext.coverage',          # Check documentation coverage
    'sphinx.ext.inheritance_diagram',  # Generate inheritance diagrams
    'sphinx_copybutton',            # Copy button for code blocks
]

# Autosummary settings
autosummary_generate = True
autosummary_imported_members = False
autosummary_generate_overwrite = False

# Autodoc settings
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__,__dict__,__module__',
    'show-inheritance': True,
    'inherited-members': False,
}
autodoc_typehints = 'description'
autodoc_class_signature = 'separated'
autodoc_member_order = 'bysource'

# Patterns for dynamically generated classes to skip
_SKIP_PATTERNS = [
    'Lines_lines',  # Dynamically generated Lines classes
    'Params_',      # Dynamically generated Params classes  
    '_lines',       # Internal lines attributes
]

def autodoc_skip_member(app, what, name, obj, skip, options):
    """Skip dynamically generated classes and internal members."""
    try:
        # Skip private members (starting with _) except __init__
        if name.startswith('_') and name != '__init__':
            return True
        
        # Skip dynamically generated classes with weird names
        try:
            obj_name = getattr(obj, '__name__', None)
            if obj_name is None:
                obj_name = type(obj).__name__
        except Exception:
            obj_name = ''
        
        for pattern in _SKIP_PATTERNS:
            if pattern in str(obj_name) or pattern in name:
                return True
        
        # Skip classes with very long names (likely dynamically generated)
        if len(name) > 50:
            return True
        
        return skip
    except Exception:
        # If any error occurs, don't skip
        return skip

# Napoleon settings for Google-style docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_type_aliases = None

# Intersphinx mapping
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'pandas': ('https://pandas.pydata.org/docs/', None),
}

# -- Internationalization (i18n) ---------------------------------------------
# Supported languages
language = 'en'  # Default language
locale_dirs = ['locales/']
gettext_compact = False
gettext_uuid = True
gettext_location = True

# Read the Docs specific settings
# Check if we're building on Read the Docs
on_rtd = os.environ.get('READTHEDOCS', None) == 'True'

# Language configuration for RTD
# RTD_LANGUAGE is set by Read the Docs build system
rtd_language = os.environ.get('READTHEDOCS_LANGUAGE', 'en')
if rtd_language:
    language = rtd_language

# Define language options for switcher
languages = [
    ('en', 'English'),
    ('zh', '中文'),
]

# -- Options for HTML output -------------------------------------------------
html_theme = 'furo'  # Modern, clean theme with good readability
html_title = f'{project} Documentation'
html_short_title = project

# Theme options
html_theme_options = {
    'light_css_variables': {
        'color-brand-primary': '#2962FF',
        'color-brand-content': '#2962FF',
    },
    'dark_css_variables': {
        'color-brand-primary': '#82B1FF',
        'color-brand-content': '#82B1FF',
    },
    'sidebar_hide_name': False,
    'navigation_with_keys': True,
    # Header icon links
    'source_repository': 'https://github.com/cloudQuant/backtrader/',
    'source_branch': 'development',
    'source_directory': 'docs/source/',
    # Announcement banner with language switcher
    'announcement': '''
        <a href="https://backtrader.readthedocs.io/en/latest/">English</a> |
        <a href="https://backtrader.readthedocs.io/zh/latest/">中文</a>
    ''' if on_rtd else None,
    # Footer links
    'footer_icons': [
        {
            'name': 'GitHub',
            'url': 'https://github.com/cloudquant/backtrader',
            'html': '''
                <svg stroke="currentColor" fill="currentColor" stroke-width="0" viewBox="0 0 16 16">
                    <path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path>
                </svg>
            ''',
            'class': '',
        },
        {
            'name': 'Gitee',
            'url': 'https://gitee.com/yunjinqi/backtrader',
            'html': '''
                <svg stroke="currentColor" fill="currentColor" stroke-width="0" viewBox="0 0 1024 1024">
                    <path d="M512 1024C229.222 1024 0 794.778 0 512S229.222 0 512 0s512 229.222 512 512-229.222 512-512 512z m259.149-568.883h-290.74a25.293 25.293 0 0 0-25.292 25.293l-0.026 63.206c0 13.952 11.315 25.293 25.267 25.293h177.024c13.978 0 25.293 11.315 25.293 25.267v12.646a75.853 75.853 0 0 1-75.853 75.853h-240.23a25.293 25.293 0 0 1-25.267-25.293V417.203a75.853 75.853 0 0 1 75.827-75.853h353.946a25.293 25.293 0 0 0 25.267-25.292l0.077-63.207a25.293 25.293 0 0 0-25.268-25.293H417.152a189.62 189.62 0 0 0-189.62 189.645V771.15c0 13.977 11.316 25.293 25.294 25.293h372.94a170.65 170.65 0 0 0 170.65-170.65V480.384a25.293 25.293 0 0 0-25.293-25.267z"></path>
                </svg>
            ''',
            'class': '',
        },
    ],
}

# Static files
html_static_path = ['_static']
html_css_files = ['custom.css']

# Logo and favicon (create these if needed)
# html_logo = '_static/logo.png'
# html_favicon = '_static/favicon.ico'

# Other HTML options
html_show_sourcelink = True
html_show_sphinx = True
html_show_copyright = True
html_last_updated_fmt = '%Y-%m-%d %H:%M:%S'

# -- Options for LaTeX output ------------------------------------------------
latex_elements = {
    'papersize': 'a4paper',
    'pointsize': '11pt',
    'preamble': r'''
\usepackage{xeCJK}
''',
}

latex_documents = [
    ('index', 'backtrader.tex', 'Backtrader Documentation',
     'Backtrader Contributors', 'manual'),
]

# -- Options for manual page output ------------------------------------------
man_pages = [
    ('index', 'backtrader', 'Backtrader Documentation',
     [author], 1)
]

# -- Options for Texinfo output ----------------------------------------------
texinfo_documents = [
    ('index', 'Backtrader', 'Backtrader Documentation',
     author, 'Backtrader', 'A Python Trading Framework.',
     'Miscellaneous'),
]

# -- Extension configuration -------------------------------------------------
todo_include_todos = True

# -- Suppress warnings for missing references --------------------------------
nitpicky = False
suppress_warnings = [
    'ref.python',
    'autosummary',
    'autodoc.import_object',
    'toc.not_included',
]

# -- Custom setup ------------------------------------------------------------
def setup(app):
    """Custom Sphinx setup."""
    app.add_css_file('custom.css')
    app.connect('autodoc-skip-member', autodoc_skip_member)

#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Modern Pandas Data Feed Implementation

This module provides modern alternatives to the traditional pandas data feeds,
using the new parameter system and avoiding metaclass dependencies.

Key improvements:
- Modern parameter validation with type safety
- Better error handling and user feedback
- Enhanced documentation and IDE support
- Cleaner code structure without metaclass complexity
"""

from backtrader.utils.py3 import filter, string_types, integer_types
from backtrader import date2num
import backtrader.feed as feed
from backtrader.parameters import ParameterDescriptor, Int, Float, Bool, String


class ModernPandasDirectData(feed.DataBase):
    """
    Modern Pandas DataFrame data feed with enhanced parameter validation.
    
    Uses a Pandas DataFrame as the feed source, iterating directly over the
    tuples returned by "itertuples". This provides better performance for
    large datasets.
    
    Key features:
    - Type-safe parameter validation
    - Enhanced error handling
    - Better documentation
    - IDE-friendly development
    
    Note:
      - The ``dataname`` parameter must be a Pandas DataFrame
      - Column indices are validated to ensure they exist in the DataFrame
      - Negative values indicate optional columns not present in the DataFrame
    """
    
    # Traditional parameter definitions for compatibility
    params = (
        ("datetime", 0),
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", 6),
        ("sessionstart", None),
        ("sessionend", None),
    )
    
    # Data field names for compatibility
    datafields = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]
    
    def __init__(self, **kwargs):
        """Initialize the modern pandas direct data feed."""
        super().__init__(**kwargs)
        self._rows = None
        
        # Initialize missing attributes for compatibility
        self._tzinput = None
        
        # Add modern parameter validation after initialization
        self._setup_modern_validation()
        self._validate_dataframe()
    
    def _setup_modern_validation(self):
        """Set up modern parameter validation."""
        # Create validators for enhanced type safety
        self._validators = {
            'datetime': Int(min_val=-1, max_val=1000),
            'open': Int(min_val=-1, max_val=1000),
            'high': Int(min_val=-1, max_val=1000),
            'low': Int(min_val=-1, max_val=1000),
            'close': Int(min_val=-1, max_val=1000),
            'volume': Int(min_val=-1, max_val=1000),
            'openinterest': Int(min_val=-1, max_val=1000),
        }
        
        # Validate current parameters
        for param_name, validator in self._validators.items():
            if hasattr(self.p, param_name):
                param_value = getattr(self.p, param_name)
                try:
                    validator(param_value)  # Call the validator function
                except ValueError as e:
                    print(f"Parameter validation warning for {param_name}: {e}")
                    # Could choose to use default value or raise error
    
    def _validate_dataframe(self):
        """Validate the DataFrame and column indices."""
        if not hasattr(self.p, 'dataname') or self.p.dataname is None:
            raise ValueError("dataname parameter must be provided and contain a pandas DataFrame")
        
        try:
            import pandas as pd
            if not isinstance(self.p.dataname, pd.DataFrame):
                raise ValueError("dataname must be a pandas DataFrame")
        except ImportError:
            raise ImportError("pandas is required for ModernPandasDirectData")
        
        # Validate column indices
        df = self.p.dataname
        max_col_index = len(df.columns) - 1
        
        for field in self.datafields:
            col_index = getattr(self.p, field, -1)
            if col_index >= 0 and col_index > max_col_index:
                raise ValueError(
                    f"Column index {col_index} for {field} is out of range. "
                    f"DataFrame has {len(df.columns)} columns (0-{max_col_index})"
                )
    
    def start(self):
        """Start the data feed."""
        super().start()
        # Reset the iterator on each start
        self._rows = self.p.dataname.itertuples()
    
    def _load(self):
        """Load the next bar from the DataFrame."""
        try:
            row = next(self._rows)
        except StopIteration:
            return False
        
        # Set the standard datafields - except for datetime
        for datafield in self.getlinealiases():
            if datafield == "datetime":
                continue
            
            # Get the column index using parameter access
            colidx = getattr(self.p, datafield, -1)
            
            if colidx < 0:
                # Column is not present -- skip
                continue
            
            try:
                # Get the line to be set
                line = getattr(self.lines, datafield)
                # Get the value from the row
                value = row[colidx]
                
                # Handle pandas Timestamp conversion
                if hasattr(value, 'to_pydatetime'):
                    # This is a datetime column that shouldn't be here
                    continue
                
                # Set the value from the row
                line[0] = value
            except (IndexError, AttributeError) as e:
                raise ValueError(f"Error setting {datafield} from column {colidx}: {e}")
        
        # Handle datetime separately
        datetime_idx = getattr(self.p, "datetime", 0)
        if datetime_idx >= 0:
            try:
                tstamp = row[datetime_idx]
                
                # Handle different datetime formats
                if hasattr(tstamp, 'to_pydatetime'):
                    # Pandas timestamp
                    dt = tstamp.to_pydatetime()
                elif isinstance(tstamp, str):
                    # String datetime - try to parse
                    import pandas as pd
                    dt = pd.to_datetime(tstamp).to_pydatetime()
                elif hasattr(tstamp, 'date') and hasattr(tstamp, 'time'):
                    # Already a datetime object
                    dt = tstamp
                else:
                    # Try to convert from numeric or other format
                    import pandas as pd
                    dt = pd.to_datetime(tstamp).to_pydatetime()
                
                dtnum = date2num(dt)
                
                # Get the datetime line and set the value
                line = getattr(self.lines, "datetime")
                line[0] = dtnum
            except Exception as e:
                raise ValueError(f"Error processing datetime from column {datetime_idx}: {e}")
        
        return True


class ModernPandasData(feed.DataBase):
    """
    Modern Pandas DataFrame data feed using column names instead of indices.
    
    Uses a Pandas DataFrame as the feed source, using column names for
    data mapping. This is more intuitive and less error-prone than index-based
    mapping.
    
    Features:
    - Column name-based mapping (more intuitive)
    - Automatic column validation
    - Support for various datetime formats
    - Enhanced error reporting
    """
    
    # Traditional parameter definitions for compatibility
    params = (
        ("datetime", "datetime"),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", "openinterest"),
        ("auto_detect_columns", True),
        ("sessionstart", None),
        ("sessionend", None),
    )
    
    # Data field names
    datafields = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]
    
    def __init__(self, **kwargs):
        """Initialize the modern pandas data feed."""
        super().__init__(**kwargs)
        self._column_mapping = {}
        self._rows = None
        
        # Initialize missing attributes for compatibility
        self._tzinput = None
        
        # Add modern parameter validation
        self._setup_modern_validation()
        self._validate_and_setup_columns()
    
    def _setup_modern_validation(self):
        """Set up modern parameter validation."""
        # Create validators for enhanced type safety
        self._validators = {
            'datetime': String(min_length=1, max_length=100),
            'open': String(min_length=1, max_length=100),
            'high': String(min_length=1, max_length=100),
            'low': String(min_length=1, max_length=100),
            'close': String(min_length=1, max_length=100),
            'volume': String(min_length=1, max_length=100),
            'openinterest': String(min_length=1, max_length=100),
            'auto_detect_columns': Bool(),
        }
        
        # Validate current parameters
        for param_name, validator in self._validators.items():
            if hasattr(self.p, param_name):
                param_value = getattr(self.p, param_name)
                try:
                    validator(param_value)  # Call the validator function
                except ValueError as e:
                    print(f"Parameter validation warning for {param_name}: {e}")
    
    def _validate_and_setup_columns(self):
        """Validate DataFrame and set up column mapping."""
        if not hasattr(self.p, 'dataname') or self.p.dataname is None:
            raise ValueError("dataname parameter must be provided and contain a pandas DataFrame")
        
        try:
            import pandas as pd
            if not isinstance(self.p.dataname, pd.DataFrame):
                raise ValueError("dataname must be a pandas DataFrame")
        except ImportError:
            raise ImportError("pandas is required for ModernPandasData")
        
        df = self.p.dataname
        available_columns = list(df.columns)
        
        # Set up column mapping
        for field in self.datafields:
            col_name = getattr(self.p, field, field)
            
            if col_name in available_columns:
                self._column_mapping[field] = col_name
            elif self.p.auto_detect_columns:
                # Try to auto-detect common variations
                detected_col = self._auto_detect_column(field, available_columns)
                if detected_col:
                    self._column_mapping[field] = detected_col
                    print(f"Auto-detected column '{detected_col}' for field '{field}'")
            
            # Validate required columns
            if field in ["datetime", "close"] and field not in self._column_mapping:
                raise ValueError(f"Required column '{field}' not found in DataFrame. "
                               f"Available columns: {available_columns}")
    
    def _auto_detect_column(self, field, available_columns):
        """Auto-detect column names for common variations."""
        # Common column name variations
        variations = {
            'datetime': ['date', 'timestamp', 'time', 'dt', 'Date', 'DateTime', 'Timestamp'],
            'open': ['Open', 'OPEN', 'o'],
            'high': ['High', 'HIGH', 'h'],
            'low': ['Low', 'LOW', 'l'],
            'close': ['Close', 'CLOSE', 'c', 'price', 'Price'],
            'volume': ['Volume', 'VOLUME', 'vol', 'Vol', 'VOL'],
            'openinterest': ['OpenInterest', 'OPENINTEREST', 'oi', 'OI']
        }
        
        if field in variations:
            for variation in variations[field]:
                if variation in available_columns:
                    return variation
        
        return None
    
    def start(self):
        """Start the data feed."""
        super().start()
        # Reset the iterator on each start
        self._rows = self.p.dataname.iterrows()
    
    def _load(self):
        """Load the next bar from the DataFrame."""
        try:
            idx, row = next(self._rows)
        except StopIteration:
            return False
        
        # Set the standard datafields - except for datetime
        for datafield in self.datafields:
            if datafield == "datetime":
                continue
            
            if datafield not in self._column_mapping:
                # Field not present in DataFrame - skip
                continue
            
            col_name = self._column_mapping[datafield]
            
            try:
                # Get the line to be set
                line = getattr(self.lines, datafield)
                # Set the value from the row
                line[0] = row[col_name]
            except (KeyError, AttributeError) as e:
                raise ValueError(f"Error setting {datafield} from column '{col_name}': {e}")
        
        # Handle datetime
        if "datetime" in self._column_mapping:
            datetime_col = self._column_mapping["datetime"]
            try:
                tstamp = row[datetime_col]
                
                # Handle various datetime formats
                if hasattr(tstamp, 'to_pydatetime'):
                    # Pandas timestamp
                    dt = tstamp.to_pydatetime()
                elif isinstance(tstamp, str):
                    # String datetime - try to parse
                    import pandas as pd
                    dt = pd.to_datetime(tstamp).to_pydatetime()
                else:
                    # Assume it's already a datetime object
                    dt = tstamp
                
                dtnum = date2num(dt)
                
                # Get the datetime line and set the value
                line = getattr(self.lines, "datetime")
                line[0] = dtnum
                
            except Exception as e:
                raise ValueError(f"Error processing datetime from column '{datetime_col}': {e}")
        
        return True


# Note: Parameters are now defined directly in the class definitions above
# This provides better compatibility with the existing metaclass system
# while still adding modern validation capabilities
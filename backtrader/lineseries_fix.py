#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""
这个文件包含修复的LineSeries.__setattr__方法，可以替换到原始文件中
"""

def fixed_setattr(self, name, value):
    """
    安全的__setattr__实现，避免递归问题
    """
    # CRITICAL FIX: Handle DotDict and similar objects without triggering KeyError
    # The hasattr() calls were causing KeyError exceptions on DotDict objects
    if name.startswith('_') or name in ('lines', 'datas', 'ddatas', 'dnames', 'params', 'p'):
        # For internal attributes and known safe attributes, set directly
        object.__setattr__(self, name, value)
        return
    
    # CRITICAL FIX: Safe hasattr check that won't trigger KeyError on DotDict
    def safe_hasattr(obj, attr):
        """Safe hasattr that won't trigger KeyError on DotDict objects"""
        try:
            # Check if this is a DotDict or similar dict-like object
            if hasattr(obj.__class__, '__getattr__') and isinstance(obj, dict):
                # For dict-like objects, check if the attribute exists without triggering __getattr__
                return attr in obj.__dict__ or attr in dir(obj.__class__)
            else:
                # For regular objects, use normal hasattr
                return hasattr(obj, attr)
        except (KeyError, AttributeError, TypeError):
            return False
    
    # CRITICAL FIX: Enhanced line assignment with safe attribute checking
    try:
        # Check if this could be an indicator assignment
        is_indicator = False
        try:
            # Safe check for indicator-like properties
            if (safe_hasattr(value, 'lines') and safe_hasattr(value, '_minperiod')) or \
               (safe_hasattr(value, '__class__') and 'Indicator' in str(value.__class__.__name__)) or \
               (safe_hasattr(value, '_ltype') and getattr(value, '_ltype', None) == 0):
                is_indicator = True
        except Exception:
            pass
        
        if is_indicator:
            print(f"LineSeries.__setattr__: Setting indicator '{name}' = {value.__class__} (value: {value})")
            print(f"LineSeries.__setattr__: Indicator '{name}' class: {value.__class__.__name__}")
            
            # Set the indicator as an attribute
            object.__setattr__(self, name, value)
            
            # CRITICAL FIX: Ensure the indicator has proper setup
            if not safe_hasattr(value, '_owner') or getattr(value, '_owner', None) is None:
                try:
                    value._owner = self
                except Exception:
                    pass
            
            # CRITICAL FIX: Add to lineiterators if not already there - 避免使用 'in' 操作符
            if safe_hasattr(self, '_lineiterators') and safe_hasattr(value, '_ltype'):
                try:
                    ltype = getattr(value, '_ltype', 0)
                    
                    # 关键修复：不使用 'in' 操作符，而是通过ID比较来检查是否已存在
                    found = False
                    for item in self._lineiterators[ltype]:
                        if id(item) == id(value):
                            found = True
                            break
                            
                    if not found:
                        self._lineiterators[ltype].append(value)
                except Exception:
                    pass
            
            return
        
        # CRITICAL FIX: Handle data assignment
        if name.startswith('data') and (safe_hasattr(value, '_name') or safe_hasattr(value, 'lines')):
            print(f"LineSeries.__setattr__: Detected indicator for '{name}': {value.__class__}")
            object.__setattr__(self, name, value)
            return
        
        # For all other assignments, use normal attribute setting
        object.__setattr__(self, name, value)
                
    except Exception as e:
        # CRITICAL FIX: If anything fails, fall back to simple attribute setting
        try:
            object.__setattr__(self, name, value)
        except Exception as e2:
            # Final fallback: store in a special dict if needed
            if not hasattr(self, '_fallback_attrs'):
                object.__setattr__(self, '_fallback_attrs', {})
            self._fallback_attrs[name] = value

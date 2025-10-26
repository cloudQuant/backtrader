# Backtrader Performance Analysis Report
## Remove-Metaprogramming Branch vs Master Branch

### Executive Summary

**Critical Performance Regression Detected:**
- **Execution Time:** Increased from **63.1s** to **108.2s** (**71.5% slower**)
- **Function Calls:** Increased from **123.3M** to **184.7M** (**49.8% more calls**)

---

## 1. Top Performance Bottlenecks

### 1.1 Attribute Access Overhead (Primary Issue)

| Function | Master Branch | Remove-Meta Branch | Increase |
|----------|---------------|-------------------|----------|
| `__getattr__` | 0.546s (1.8M calls) | **7.886s (2.6M calls)** | **+14x time** |
| `__setattr__` | Not in top 50 | **5.984s (4.4M calls)** | **NEW HOTSPOT** |
| `hasattr()` builtin | 0.096s (351K calls) | **6.289s (31.9M calls)** | **+65x time, 90x calls** |

**Root Cause:** The removal of metaclass functionality has forced complex attribute resolution into `__getattr__` and `__setattr__` methods which are called millions of times during execution.

### 1.2 String Operations Overhead

| Function | Master Branch | Remove-Meta Branch | Increase |
|----------|---------------|-------------------|----------|
| `str.startswith()` | Minimal | **2.163s (10.7M calls)** | **NEW HOTSPOT** |
| `str.lower()` | Minimal | **0.434s (1.7M calls)** | **NEW HOTSPOT** |

**Root Cause:** Extensive string checking in `__getattr__` and parameter handling code.

### 1.3 Other Significant Changes

| Function | Master Branch | Remove-Meta Branch | Change |
|----------|---------------|-------------------|--------|
| `linebuffer.forward` | 5.419s | 6.621s | +22% |
| `len()` builtin | 5.052s (16.5M) | 2.957s (13.5M) | -41% ✓ |
| `lineiterator._next` | 4.292s | Better distributed | ✓ |

---

## 2. Detailed Analysis

### 2.1 __getattr__ Performance Issues

**File:** `backtrader/lineseries.py:781-886`

**Problems:**
1. **Recursion Guard Overhead:** Uses `object.__setattr__` to set/unset `_in_getattr` flag on every call
2. **Multiple getattr() Calls:** Line 792 uses `getattr(self, '_in_getattr', False)` which can trigger more `__getattr__` calls
3. **Nested Try-Except Blocks:** Deep nesting creates overhead (5+ levels deep)
4. **Repeated Attribute Lookups:** Each attribute check can trigger more `__getattr__` calls
5. **No Caching:** Repeated lookups for same attributes (e.g., `_owner`, `data0`)

**Code Example:**
```python
def __getattr__(self, name):
    # Sets recursion guard - overhead!
    object.__setattr__(self, '_in_getattr', True)
    
    try:
        # Multiple nested try-except blocks
        if name.startswith('data'):  # String operation
            try:
                datas = self.datas  # May trigger __getattr__
                try:
                    owner = self._owner  # May trigger __getattr__
                    try:
                        owner_datas = owner.datas  # May trigger __getattr__
                        # ... more nesting
```

### 2.2 __setattr__ Performance Issues

**File:** `backtrader/lineseries.py:888-976`

**Problems:**
1. **Indicator Detection:** Tries to access `value.lines` and `value._minperiod` on every attribute set
2. **String Operations:** `'Indicator' in str(value.__class__.__name__)` is expensive
3. **List Iteration:** Iterates through `lineiterators[ltype]` checking `id()` equality
4. **Multiple Try-Except Blocks:** Exception handling overhead

**Code Example:**
```python
def __setattr__(self, name, value):
    try:
        is_indicator = False
        try:
            _ = value.lines       # Attribute access
            _ = value._minperiod  # Another attribute access
            is_indicator = True
        except AttributeError:
            try:
                is_indicator = 'Indicator' in str(value.__class__.__name__)  # String operation!
```

### 2.3 hasattr() Explosion

**Problem:** Code uses `hasattr()` extensively for feature detection. In Python, `hasattr(obj, 'attr')` internally:
1. Calls `getattr(obj, 'attr')`
2. If AttributeError is raised, returns False
3. Otherwise returns True

With slow `__getattr__`, every `hasattr()` call becomes expensive.

**Evidence:**
- Master: 351,114 hasattr() calls
- Remove-meta: **31,946,160 hasattr() calls** (90x increase!)

**Where it's used:**
- Line 544: `if hasattr(cls, name):`
- Line 548: `if hasattr(class_attr, '__get__'):`
- Parameter handling code
- Indicator/data detection

---

## 3. Optimization Recommendations

### Priority 1: Fix __getattr__ (Expected: -5s)

1. **Add Attribute Cache:**
```python
def __getattr__(self, name):
    # Check cache first
    try:
        cache = object.__getattribute__(self, '_attr_cache')
        if name in cache:
            return cache[name]
    except AttributeError:
        cache = {}
        object.__setattr__(self, '_attr_cache', cache)
    
    # ... rest of logic
    # Cache result before returning
    cache[name] = result
    return result
```

2. **Use __dict__ Instead of Recursion Guard:**
```python
def __getattr__(self, name):
    # Use __dict__ directly - much faster
    if '_in_getattr' in self.__dict__:
        raise AttributeError(...)
    self.__dict__['_in_getattr'] = True
    try:
        # ... logic
    finally:
        self.__dict__.pop('_in_getattr', None)
```

3. **Replace getattr() with object.__getattribute__():**
```python
# SLOW:
if getattr(self, '_in_getattr', False):

# FAST:
try:
    in_getattr = object.__getattribute__(self, '_in_getattr')
except AttributeError:
    in_getattr = False
if in_getattr:
```

4. **Early Exit for Common Cases:**
```python
def __getattr__(self, name):
    # Fast path for most common attributes
    if name in ('_owner', '_clock', 'data0', 'data1'):
        # Handle directly without complex logic
```

### Priority 2: Fix __setattr__ (Expected: -4s)

1. **Cache Indicator Detection:**
```python
def __setattr__(self, name, value):
    if name.startswith('_'):
        object.__setattr__(self, name, value)
        return
    
    # Check type cache
    value_type = type(value)
    try:
        is_indicator = self._type_cache.get(value_type, None)
    except AttributeError:
        self._type_cache = {}
        is_indicator = None
    
    if is_indicator is None:
        is_indicator = hasattr(value, 'lines') and hasattr(value, '_minperiod')
        self._type_cache[value_type] = is_indicator
```

2. **Use set() for lineiterators Check:**
```python
# SLOW: Linear search
for item in lineiterators[ltype]:
    if id(item) == id(value):
        found = True

# FAST: Use set
if id(value) not in self._lineiterator_ids:
    lineiterators[ltype].append(value)
    self._lineiterator_ids.add(id(value))
```

3. **Remove String Type Checking:**
```python
# REMOVE THIS - too slow:
is_indicator = 'Indicator' in str(value.__class__.__name__)

# Use duck typing instead
```

### Priority 3: Reduce hasattr() Calls (Expected: -4s)

1. **Replace hasattr() with try-except:**
```python
# SLOW:
if hasattr(obj, 'attr'):
    value = obj.attr

# FAST:
try:
    value = obj.attr
except AttributeError:
    value = None
```

2. **Use __dict__ or slots:**
```python
# SLOW:
if hasattr(self, '_owner'):

# FAST:
if '_owner' in self.__dict__:
```

### Priority 4: Optimize Common Patterns

1. **Lazy Initialization of Helper Objects:**
```python
# Don't create MinimalData() every time
# Create once and reuse
_minimal_data_singleton = MinimalData()

def __getattr__(self, name):
    if name.startswith('data'):
        return _minimal_data_singleton
```

2. **Pre-compile Regular Expressions:**
```python
import re
DATA_PATTERN = re.compile(r'^data\d+$')

def __getattr__(self, name):
    if DATA_PATTERN.match(name):
        # ...
```

---

## 4. Expected Performance Improvements

| Optimization | Expected Time Saved | Difficulty |
|--------------|-------------------|------------|
| Fix __getattr__ caching | -5s | Medium |
| Fix __setattr__ caching | -4s | Medium |
| Reduce hasattr() calls | -4s | Easy |
| Optimize string ops | -2s | Easy |
| Optimize linebuffer.forward | -1s | Hard |
| **Total** | **-16s** | |

**Target:** Reduce execution time from 108.2s to ~92s (15% improvement from current, still slower than master 63s but significant progress)

---

## 5. Additional Observations

### Positive Changes:
- ✅ `len()` calls reduced by 41% - good optimization
- ✅ Better code distribution reduces some hot spots

### Areas for Further Investigation:
- Why is `linebuffer.forward` slower? (5.4s → 6.6s)
- Can we restore some metaclass benefits without full metaprogramming?
- Are there NumPy operations that can be optimized? (3.9s in mean calculations)

---

## 6. Conclusion

The performance regression is primarily caused by **attribute access overhead** introduced when removing metaclasses. The `__getattr__` and `__setattr__` methods are doing far too much work and being called millions of times.

**Key Metrics:**
- **71.5% slower overall**
- **14x slower attribute access**
- **90x more hasattr() calls**

**Recommended Action:** Implement Priority 1-3 optimizations immediately, focusing on:
1. Attribute caching in `__getattr__`
2. Type caching in `__setattr__`
3. Replacing `hasattr()` with `try-except`

These changes should recover approximately **15s** of the **45s** performance loss.


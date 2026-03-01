# Technology Stack

## Core Technologies

| Category | Technology | Version | Justification |

|----------|-----------|---------|---------------|

| **Language**| Python | 3.8-3.13 | Core development language |

|**Package Manager**| setuptools | 40.0+ | Package distribution |

|**Build Tool**| Cython | 0.29.0+ | Performance optimization (being phased out for C++) |

## Data Processing

| Category | Technology | Version | Purpose |

|----------|-----------|---------|---------|

|**Data Manipulation**| pandas | 1.3.0+ | Time series data processing |

|**Numerical Computing**| numpy | 1.20.0+ | Numerical operations |

|**Scientific Computing**| scipy | 1.5.0+ | Advanced mathematical functions |

|**Statistics**| statsmodels | 0.12.0+ | Statistical analysis |

## Visualization

| Category | Technology | Version | Purpose |

|----------|-----------|---------|---------|

|**Static Charts**| matplotlib | 3.3.0+ | Traditional plotting for reports |

|**Interactive Charts**| plotly | 5.0.0+ | Interactive visualization (100k+ points) |

|**Web Charts**| pyecharts | 1.9.0+ | Browser-based charts |

|**Dashboard**| dash | 2.0.0+ | Web dashboard framework |

## Date & Time

| Category | Technology | Version | Purpose |

|----------|-----------|---------|---------|

|**Date Utilities**| python-dateutil | 2.8.0+ | Date parsing |

|**Timezones**| pytz | 2021.1+ | Timezone handling |

|**Local Time**| tzlocal | 2.1+ | Local timezone detection |

## Testing Framework

| Category | Technology | Version | Purpose |

|----------|-----------|---------|---------|

|**Test Runner**| pytest | 6.0.0+ | Core testing framework |

|**Benchmarking**| pytest-benchmark | 3.4.0+ | Performance testing |

|**Parallel Execution**| pytest-xdist | 2.3.0+ | Parallel test execution |

|**Coverage**| pytest-cov | 2.12.0+ | Code coverage |

|**Async Testing**| pytest-asyncio | 0.15.0+ | Async test support |

|**Mocking**| pytest-mock | 3.6.0+ | Test mocking |

|**HTML Reports**| pytest-html | 3.1.0+ | HTML test reports |

|**Timeout**| pytest-timeout | 2.1.0+ | Test timeout control |

## Optional Dependencies

| Category | Technology | Status | Notes |

|----------|-----------|--------|-------|

|**JIT Compilation**| numba | Disabled | Platform compatibility issues |

|**Logging**| spdlog | Disabled | Replaced with SpdLogManager |

|**JSON**| python-rapidjson | Disabled | Optional |

|**China Data**| ctpbee | Optional | Requires C++ build |

|**China Data**| akshare | Optional | Network issues in CI |

|**External API**| bt_api_py | Optional | External package |

## Live Trading APIs

| API | Technology | Purpose |

|-----|-----------|---------|

|**Crypto Exchanges**| CCXT | Unified crypto exchange API |

|**China Futures**| ctp-python | Native CTP API (not ctpbee) |

## Development Tools

| Category | Tool | Version | Purpose |

|----------|------|---------|---------|

|**Formatter**| Black | latest | Code formatting (line-length: 124) |

|**Linter**| Ruff | 0.14.6+ | Fast Python linter |

|**Type Checker**| mypy | latest | Static type checking |

|**Security**| bandit | latest | Security scanning |

|**Import Sorter** | isort | latest | Import organization |

## Architecture Pattern

- *Type**: Event-Driven Backtesting Framework

- *Key Architectural Patterns**:
1. **Line System**: Circular buffer for time series data
2. **Phase System**: prenext → nextstart → next execution phases
3. **Observer Pattern**: Observers for data collection
4. **Strategy Pattern**: Pluggable trading strategies
5. **Broker Pattern**: Abstract order execution

- *Post-Metaclass Architecture**:
- Explicit `donew()` initialization pattern
- Mixin-based inheritance instead of metaclasses
- 45% performance improvement over original backtrader

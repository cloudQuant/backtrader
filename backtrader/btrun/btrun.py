#!/usr/bin/env python
"""btrun - Command-line runner for Backtrader backtesting framework.

This module provides a command-line interface for running backtrader strategies
from the command line. It supports loading data feeds, strategies, indicators,
observers, analyzers, and signals from both built-in modules and external files.

The main entry point is the `btrun()` function which parses command-line arguments
and executes a complete backtest with the specified configuration.

Example:
    Running from command line:
    $ python -m backtrader.btrun.btrun --data data.csv --strategy MyStrategy

    Running programmatically:
    >>> from backtrader.btrun import btrun
    >>> btrun('--data data.csv --strategy MyStrategy')
"""

import argparse
import datetime
import inspect
import random
import string
import sys

from .. import analyzers as analyzers_module
from .. import indicators as indicators_module
from .. import observers as observers_module
from .. import signal as signal_module
from .. import signals as signals_module
from .. import strategies as strategies_module
from ..analyzer import Analyzer
from ..cerebro import Cerebro
from ..dataseries import TimeFrame
from ..feeds.btcsv import BacktraderCSVData
from ..feeds.mt4csv import MT4CSVData
from ..feeds.sierrachart import SierraChartCSVData
from ..feeds.vchartcsv import VChartCSVData
from ..feeds.vchartfile import VChartFile
from ..feeds.yahoo import YahooFinanceCSVData, YahooFinanceData
from ..feeds.yahoounreversed import YahooFinanceCSVData as YahooFinanceCSVDataUnreversed
from ..indicator import Indicator
from ..observer import Observer
from ..strategy import Strategy
from ..writer import WriterFile

try:
    from ..feeds.vcdata import VCData
except ImportError:
    VCData = None

try:
    from ..feeds.ibdata import IBData
except ImportError:
    IBData = None

try:
    from ..feeds.oanda import OandaData
except ImportError:
    OandaData = None


DATAFORMATS = dict(
    btcsv=BacktraderCSVData,
    vchartcsv=VChartCSVData,
    vcfile=VChartFile,
    sierracsv=SierraChartCSVData,
    mt4csv=MT4CSVData,
    yahoocsv=YahooFinanceCSVData,
    yahoocsv_unreversed=YahooFinanceCSVDataUnreversed,
    yahoo=YahooFinanceData,
)

if VCData is not None:
    DATAFORMATS["vcdata"] = VCData

if IBData is not None:
    DATAFORMATS["ibdata"] = (IBData,)

if OandaData is not None:
    DATAFORMATS["oandadata"] = (OandaData,)

TIMEFRAMES = dict(
    microseconds=TimeFrame.MicroSeconds,
    seconds=TimeFrame.Seconds,
    minutes=TimeFrame.Minutes,
    days=TimeFrame.Days,
    weeks=TimeFrame.Weeks,
    months=TimeFrame.Months,
    years=TimeFrame.Years,
)


def btrun(pargs=""):
    """Run a backtest with the specified configuration.

    This is the main entry point for command-line backtesting. It parses arguments,
    sets up the Cerebro engine with data feeds, strategies, indicators, observers,
    and analyzers, then executes the backtest and optionally displays results.

    Args:
        pargs (str or list, optional): Command-line arguments as a string or list.
            If empty, uses sys.argv. Defaults to "".

    The function performs the following steps:
        1. Parse command-line arguments
        2. Create Cerebro instance with specified parameters
        3. Add data feeds (with optional resampling/replaying)
        4. Add signals, strategies, indicators, observers, and analyzers
        5. Configure broker settings (cash, commission, slippage)
        6. Add writers for output
        7. Run the backtest
        8. Optionally print analyzer results and plot results
    """
    args = parse_args(pargs)

    if args.flush:
        pass

    stdstats = not args.nostdstats

    cer_kwargs_str = args.cerebro
    cer_kwargs = eval("dict(" + cer_kwargs_str + ")")
    if "stdstats" not in cer_kwargs:
        cer_kwargs.update(stdstats=stdstats)

    cerebro = Cerebro(**cer_kwargs)

    if args.resample is not None or args.replay is not None:
        if args.resample is not None:
            tfcp = args.resample.split(":")
        elif args.replay is not None:
            tfcp = args.replay.split(":")

        # compression may be skipped and it will default to 1
        if len(tfcp) == 1 or tfcp[1] == "":
            tf, cp = tfcp[0], 1
        else:
            tf, cp = tfcp

        cp = int(cp)  # convert any value to int
        tf = TIMEFRAMES.get(tf, None)

    for data in getdatas(args):
        if args.resample is not None:
            cerebro.resampledata(data, timeframe=tf, compression=cp)
        elif args.replay is not None:
            cerebro.replaydata(data, timeframe=tf, compression=cp)
        else:
            cerebro.adddata(data)

    # get and add signals
    signals = getobjects(args.signals, Indicator, signals_module, issignal=True)
    for sig, kwargs, sigtype in signals:
        stype = getattr(signal_module, "SIGNAL_" + sigtype.upper())
        cerebro.add_signal(stype, sig, **kwargs)

    # get and add strategies
    strategies = getobjects(args.strategies, Strategy, strategies_module)
    for strat, kwargs in strategies:
        cerebro.addstrategy(strat, **kwargs)

    inds = getobjects(args.indicators, Indicator, indicators_module)
    for ind, kwargs in inds:
        cerebro.addindicator(ind, **kwargs)

    obs = getobjects(args.observers, Observer, observers_module)
    for ob, kwargs in obs:
        cerebro.addobserver(ob, **kwargs)

    ans = getobjects(args.analyzers, Analyzer, analyzers_module)
    for an, kwargs in ans:
        cerebro.addanalyzer(an, **kwargs)

    setbroker(args, cerebro)

    for wrkwargs_str in args.writers or []:
        wrkwargs = eval("dict(" + wrkwargs_str + ")")
        cerebro.addwriter(WriterFile, **wrkwargs)

    ans = getfunctions(args.hooks, Cerebro)
    for hook, kwargs in ans:
        hook(cerebro, **kwargs)
    runsts = cerebro.run()
    runst = runsts[0]  # single strategy and no optimization

    if args.pranalyzer or args.ppranalyzer:
        if runst.analyzers:
            print("====================")
            print("== Analyzers")
            print("====================")
            for name, analyzer in runst.analyzers.getitems():
                if args.pranalyzer:
                    analyzer.print()
                elif args.ppranalyzer:
                    print("##########")
                    print(name)
                    print("##########")
                    analyzer.pprint()

    if args.plot:
        pkwargs = dict(style="bar")
        if args.plot is not True:
            # evaluates to True but is not "True" - args were passed
            ekwargs = eval("dict(" + args.plot + ")")
            pkwargs.update(ekwargs)

        # cerebro.plot(numfigs=args.plotfigs, style=args.plotstyle)
        cerebro.plot(**pkwargs)


def setbroker(args, cerebro):
    """Configure broker settings from parsed command-line arguments.

    Sets broker cash, commission scheme parameters, and slippage settings
    on the cerebro instance's broker.

    Args:
        args (argparse.Namespace): Parsed command-line arguments containing
            broker configuration options like cash, commission, margin, mult,
            interest, slippage, etc.
        cerebro (Cerebro): Cerebro instance whose broker will be configured.

    The following broker settings are configured:
        - Cash: Initial capital via args.cash
        - Commission: Trading commission via args.commission, args.margin, args.mult
        - Interest: Credit interest rate via args.interest, args.interest_long
        - Slippage: Price slippage model via args.slip_perc or args.slip_fixed
    """
    broker = cerebro.getbroker()

    if args.cash is not None:
        broker.setcash(args.cash)

    commkwargs = dict()
    if args.commission is not None:
        commkwargs["commission"] = args.commission
    if args.margin is not None:
        commkwargs["margin"] = args.margin
    if args.mult is not None:
        commkwargs["mult"] = args.mult
    if args.interest is not None:
        commkwargs["interest"] = args.interest
    if args.interest_long is not None:
        commkwargs["interest_long"] = args.interest_long

    if commkwargs:
        broker.setcommission(**commkwargs)

    if args.slip_perc is not None:
        cerebro.broker.set_slippage_perc(
            args.slip_perc,
            slip_open=args.slip_open,
            slip_match=not args.no_slip_match,
            slip_out=args.slip_out,
        )
    elif args.slip_fixed is not None:
        cerebro.broker.set_slippage_fixed(
            args.slip_fixed,
            slip_open=args.slip_open,
            slip_match=not args.no_slip_match,
            slip_out=args.slip_out,
        )


def getdatas(args):
    """Create data feed instances from command-line arguments.

    Parses the data format, date range, timeframe, and compression settings
    from the arguments, then creates data feed instances for each specified
    data file.

    Args:
        args (argparse.Namespace): Parsed command-line arguments containing
            data configuration options including:
            - data: List of data file paths
            - format: Data format type (e.g., 'btcsv', 'yahoo')
            - fromdate: Start date filter
            - todate: End date filter
            - timeframe: Timeframe for the data
            - compression: Compression factor

    Returns:
        list: List of data feed instances ready to be added to Cerebro.
    """
    # Get the data feed class from the global dictionary
    dfcls = DATAFORMATS[args.format]

    # Prepare some args
    dfkwargs = dict()
    if args.format == "yahoo_unreversed":
        dfkwargs["reverse"] = True

    fmtstr = "%Y-%m-%d"
    if args.fromdate:
        dtsplit = args.fromdate.split("T")
        if len(dtsplit) > 1:
            fmtstr += "T%H:%M:%S"

        fromdate = datetime.datetime.strptime(args.fromdate, fmtstr)
        dfkwargs["fromdate"] = fromdate

    fmtstr = "%Y-%m-%d"
    if args.todate:
        dtsplit = args.todate.split("T")
        if len(dtsplit) > 1:
            fmtstr += "T%H:%M:%S"
        todate = datetime.datetime.strptime(args.todate, fmtstr)
        dfkwargs["todate"] = todate

    if args.timeframe is not None:
        dfkwargs["timeframe"] = TIMEFRAMES[args.timeframe]

    if args.compression is not None:
        dfkwargs["compression"] = args.compression

    datas = list()
    for dname in args.data:
        dfkwargs["dataname"] = dname
        data = dfcls(**dfkwargs)
        datas.append(data)

    return datas


def getmodclasses(mod, clstype, clsname=None):
    """Get classes from a module that match a specific type.

    Searches through a module to find all classes that are subclasses of
    a given type. Optionally filters by class name.

    Args:
        mod (module): Python module to search for classes.
        clstype (type): Base class type to filter by (e.g., Strategy, Indicator).
        clsname (str, optional): Specific class name to find. If None,
            returns all matching classes. Defaults to None.

    Returns:
        list: List of class objects that match the criteria. If clsname is
            specified, returns a list with at most one element.
    """
    clsmembers = inspect.getmembers(mod, inspect.isclass)

    clslist = list()
    for name, cls in clsmembers:
        if not issubclass(cls, clstype):
            continue

        if clsname:
            if clsname == name:
                clslist.append(cls)
                break
        else:
            clslist.append(cls)

    return clslist


def getmodfunctions(mod, funcname=None):
    """Get functions from a module, optionally filtering by name.

    Searches through a module to find all functions and methods. Optionally
    filters by function name.

    Args:
        mod (module): Python module to search for functions.
        funcname (str, optional): Specific function name to find. If None,
            returns all functions and methods. Defaults to None.

    Returns:
        list: List of function/method objects that match the criteria. If
            funcname is specified, returns a list with at most one element.
    """
    members = inspect.getmembers(mod, inspect.isfunction) + inspect.getmembers(
        mod, inspect.ismethod
    )

    funclist = list()
    for name, member in members:
        if funcname:
            if name == funcname:
                funclist.append(member)
                break
        else:
            funclist.append(member)

    return funclist


def loadmodule(modpath, modname=""):
    """Load a Python module from a file path.

    Dynamically loads a Python module from a file path. Supports both Python 2
    and Python 3 using different loading mechanisms. If no module name is provided,
    generates a random 10-character alphanumeric name.

    Args:
        modpath (str): Path to the Python module file. If it doesn't end with
            '.py', the extension will be automatically appended.
        modname (str, optional): Name to assign to the loaded module. If None or
            empty, a random name is generated. Defaults to "".

    Returns:
        tuple: A tuple containing:
            - mod (module or None): The loaded module object, or None if loading failed.
            - e (Exception or None): Exception object if loading failed, None otherwise.
    """
    # generate a random name for the module

    if not modpath.endswith(".py"):
        modpath += ".py"

    if not modname:
        chars = string.ascii_uppercase + string.digits
        modname = "".join(random.choice(chars) for _ in range(10))

    version = (sys.version_info[0], sys.version_info[1])

    if version < (3, 3):
        mod, e = loadmodule2(modpath, modname)
    else:
        mod, e = loadmodule3(modpath, modname)

    return mod, e


def loadmodule2(modpath, modname):
    """Load a Python module using the deprecated imp module (Python 2.x).

    This function is used for Python versions < 3.3 to load modules from
    file paths using the imp module, which is deprecated but was the standard
    method before importlib.

    Args:
        modpath (str): Path to the Python module file.
        modname (str): Name to assign to the loaded module.

    Returns:
        tuple: A tuple containing:
            - mod (module or None): The loaded module object, or None if loading failed.
            - e (Exception or None): Exception object if loading failed, None otherwise.
    """
    import imp

    try:
        mod = imp.load_source(modname, modpath)
    except Exception as e:
        return None, e

    return mod, None


def loadmodule3(modpath, modname):
    """Load a Python module using importlib.machinery (Python 3.3+).

    This function is used for Python versions >= 3.3 to load modules from
    file paths using importlib.machinery.SourceFileLoader, which is the
    modern replacement for the deprecated imp module.

    Args:
        modpath (str): Path to the Python module file.
        modname (str): Name to assign to the loaded module.

    Returns:
        tuple: A tuple containing:
            - mod (module or None): The loaded module object, or None if loading failed.
            - e (Exception or None): Exception object if loading failed, None otherwise.
    """
    import importlib.machinery

    try:
        loader = importlib.machinery.SourceFileLoader(modname, modpath)
        mod = loader.load_module()
    except Exception as e:
        return None, e

    return mod, None


def getobjects(iterable, clsbase, modbase, issignal=False):
    """Load and instantiate objects from module specifications.

    Parses a list of object specifications in the format 'module:name:kwargs',
    loads the corresponding modules, finds the requested classes, and returns
    them with their associated kwargs. Used for strategies, indicators,
    observers, analyzers, and signals.

    Args:
        iterable (list): List of object specification strings. Each string can be:
            - 'module:name:kwargs' - Load specific class from module with kwargs
            - 'module:name' - Load specific class from module
            - 'module' - Load first matching class from module
            - ':name' - Load class from built-in module (modbase)
            - For signals: 'signaltype+module:name:kwargs'
        clsbase (type): Base class type to filter by (e.g., Strategy, Indicator).
        modbase (module): Default module to use when module path is omitted.
        issignal (bool, optional): Whether processing signals. If True, parses
            signal type prefix (e.g., 'longshort+'). Defaults to False.

    Returns:
        list: List of tuples containing:
            - For signals: (class, kwargs_dict, signal_type)
            - For others: (class, kwargs_dict)

    The function will call sys.exit(1) if module loading or class finding fails.
    """
    retobjects = list()

    for item in iterable or []:
        if issignal:
            sigtokens = item.split("+", 1)
            if len(sigtokens) == 1:  # no + seen
                sigtype = "longshort"
            else:
                sigtype, item = sigtokens

        tokens = item.split(":", 1)

        if len(tokens) == 1:
            modpath = tokens[0]
            name = ""
            kwargs = dict()
        else:
            modpath, name = tokens
            kwtokens = name.split(":", 1)
            if len(kwtokens) == 1:
                # no '(' found
                kwargs = dict()
            else:
                name = kwtokens[0]
                kwtext = "dict(" + kwtokens[1] + ")"
                kwargs = eval(kwtext)

        if modpath:
            mod, e = loadmodule(modpath)

            if not mod:
                print("")
                print("Failed to load module %s:" % modpath, e)
                sys.exit(1)
        else:
            mod = modbase

        loaded = getmodclasses(mod=mod, clstype=clsbase, clsname=name)

        if not loaded:
            print(f"No class {str(name)} / module {modpath}")
            sys.exit(1)

        if issignal:
            retobjects.append((loaded[0], kwargs, sigtype))
        else:
            retobjects.append((loaded[0], kwargs))

    return retobjects


def getfunctions(iterable, modbase):
    """Load and retrieve function objects from module specifications.

    Parses a list of function specifications in the format 'module:name:kwargs',
    loads the corresponding modules, finds the requested functions, and returns
    them with their associated kwargs. Used for cerebro hook functions.

    Args:
        iterable (list): List of function specification strings. Each string can be:
            - 'module:name:kwargs' - Load specific function from module with kwargs
            - 'module:name' - Load specific function from module
            - 'module' - Load first function from module
            - ':name' - Load built-in cerebro method (e.g., ':addtz')
        modbase (module): Default module to use when module path is omitted
            (typically Cerebro for built-in methods).

    Returns:
        list: List of tuples containing:
            - (function, kwargs_dict): Function object and its keyword arguments

    The function will call sys.exit(1) if module loading or function finding fails.
    """
    retfunctions = list()

    for item in iterable or []:
        tokens = item.split(":", 1)

        if len(tokens) == 1:
            modpath = tokens[0]
            name = ""
            kwargs = dict()
        else:
            modpath, name = tokens
            kwtokens = name.split(":", 1)
            if len(kwtokens) == 1:
                # no '(' found
                kwargs = dict()
            else:
                name = kwtokens[0]
                kwtext = "dict(" + kwtokens[1] + ")"
                kwargs = eval(kwtext)

        if modpath:
            mod, e = loadmodule(modpath)

            if not mod:
                print("")
                print("Failed to load module %s:" % modpath, e)
                sys.exit(1)
        else:
            mod = modbase

        loaded = getmodfunctions(mod=mod, funcname=name)

        if not loaded:
            print(f"No function {str(name)} / module {modpath}")
            sys.exit(1)

        retfunctions.append((loaded[0], kwargs))

    return retfunctions


def parse_args(pargs=""):
    """Parse command-line arguments for the btrun script.

    Creates an argument parser and defines all command-line options for the
    backtrader runner, including data feeds, strategies, indicators, observers,
    analyzers, signals, broker settings, and output options.

    Args:
        pargs (str or list, optional): Command-line arguments to parse. If empty
            string, parses from sys.argv. Can be a string or list of strings.
            Defaults to "".

    Returns:
        argparse.Namespace: Parsed command-line arguments object containing all
            the configuration options for the backtest.

    The parser defines the following argument groups:
        - Data options: --data, --format, --fromdate, --todate, --timeframe,
          --compression, --resample, --replay
        - Cerebro options: --cerebro, --nostdstats
        - Strategy options: --strategy
        - Signals: --signal
        - Observers and statistics: --observer
        - Analyzers: --analyzer, --pranalyzer, --ppranalyzer
        - Indicators: --indicator
        - Writers: --writer
        - Cash and Commission: --cash, --commission, --margin, --mult,
          --interest, --interest_long
        - Slippage: --slip_perc, --slip_fixed, --slip_open, --no-slip_match,
          --slip_out
        - Output: --flush, --plot
        - Hooks: --hook
    """
    parser = argparse.ArgumentParser(
        description="Backtrader Run Script",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    group = parser.add_argument_group(title="Data options")
    # Data options
    group.add_argument(
        "--data", "-d", action="append", required=True, help="Data files to be added to the system"
    )

    group = parser.add_argument_group(title="Cerebro options")
    group.add_argument(
        "--cerebro",
        "-cer",
        metavar="kwargs",
        required=False,
        const="",
        default="",
        nargs="?",
        help=(
            "The argument can be specified with the following form:\n"
            "\n"
            "  - kwargs\n"
            "\n"
            '    Example: "preload=True" which set its to True\n'
            "\n"
            "The passed kwargs will be passed directly to the cerebro\n"
            "instance created for the execution\n"
            "\n"
            "The available kwargs to cerebro are:\n"
            "  - preload (default: True)\n"
            "  - runonce (default: True)\n"
            "  - maxcpus (default: None)\n"
            "  - stdstats (default: True)\n"
            "  - live (default: False)\n"
            "  - exactbars (default: False)\n"
            "  - preload (default: True)\n"
            "  - writer (default False)\n"
            "  - oldbuysell (default False)\n"
            "  - tradehistory (default False)\n"
        ),
    )

    group.add_argument(
        "--nostdstats", action="store_true", help="Disable the standard statistics observers"
    )

    datakeys = list(DATAFORMATS)
    group.add_argument(
        "--format",
        "--csvformat",
        "-c",
        required=False,
        default="btcsv",
        choices=datakeys,
        help="CSV Format",
    )

    group.add_argument(
        "--fromdate",
        "-f",
        required=False,
        default=None,
        help="Starting date in YYYY-MM-DD[THH:MM:SS] format",
    )

    group.add_argument(
        "--todate",
        "-t",
        required=False,
        default=None,
        help="Ending date in YYYY-MM-DD[THH:MM:SS] format",
    )

    group.add_argument(
        "--timeframe",
        "-tf",
        required=False,
        default="days",
        choices=TIMEFRAMES.keys(),
        help="Ending date in YYYY-MM-DD[THH:MM:SS] format",
    )

    group.add_argument(
        "--compression",
        "-cp",
        required=False,
        default=1,
        type=int,
        help="Ending date in YYYY-MM-DD[THH:MM:SS] format",
    )

    group = parser.add_mutually_exclusive_group(required=False)

    group.add_argument(
        "--resample",
        "-rs",
        required=False,
        default=None,
        help="resample with timeframe:compression values",
    )

    group.add_argument(
        "--replay",
        "-rp",
        required=False,
        default=None,
        help="replay with timeframe:compression values",
    )

    group.add_argument(
        "--hook",
        dest="hooks",
        action="append",
        required=False,
        metavar="module:hookfunction:kwargs",
        help=(
            "This option can be specified multiple times.\n"
            "\n"
            "The argument can be specified with the following form:\n"
            "\n"
            "  - module:hookfunction:kwargs\n"
            "\n"
            "    Example: mymod:myhook:a=1,b=2\n"
            "\n"
            "kwargs is optional\n"
            "\n"
            "If module is omitted then hookfunction will be sought\n"
            "as the built-in cerebro method. Example:\n"
            "\n"
            "  - :addtz:tz=America/St_Johns\n"
            "\n"
            "If name is omitted, then the 1st function found in the\n"
            "mod will be used. Such as in:\n"
            "\n"
            "  - module or module::kwargs\n"
            "\n"
            "The function specified will be called, with cerebro\n"
            "instance passed as the first argument together with\n"
            "kwargs, if any were specified. This allows to customize\n"
            "cerebro, beyond options provided by this script\n\n"
        ),
    )

    # Module where to read the strategy from
    group = parser.add_argument_group(title="Strategy options")
    group.add_argument(
        "--strategy",
        "-st",
        dest="strategies",
        action="append",
        required=False,
        metavar="module:name:kwargs",
        help=(
            "This option can be specified multiple times.\n"
            "\n"
            "The argument can be specified with the following form:\n"
            "\n"
            "  - module:classname:kwargs\n"
            "\n"
            "    Example: mymod:myclass:a=1,b=2\n"
            "\n"
            "kwargs is optional\n"
            "\n"
            "If module is omitted then class name will be sought in\n"
            "the built-in strategies module. Such as in:\n"
            "\n"
            "  - :name:kwargs or :name\n"
            "\n"
            "If name is omitted, then the 1st strategy found in the mod\n"
            "will be used. Such as in:\n"
            "\n"
            "  - module or module::kwargs"
        ),
    )

    # Module where to read the strategy from
    group = parser.add_argument_group(title="Signals")
    group.add_argument(
        "--signal",
        "-sig",
        dest="signals",
        action="append",
        required=False,
        metavar="module:signaltype:name:kwargs",
        help=(
            "This option can be specified multiple times.\n"
            "\n"
            "The argument can be specified with the following form:\n"
            "\n"
            "  - signaltype:module:signaltype:classname:kwargs\n"
            "\n"
            "    Example: longshort+mymod:myclass:a=1,b=2\n"
            "\n"
            "signaltype may be ommited: longshort will be used\n"
            "\n"
            "    Example: mymod:myclass:a=1,b=2\n"
            "\n"
            "kwargs is optional\n"
            "\n"
            "signaltype will be uppercased to match the defintions\n"
            "fromt the backtrader.signal module\n"
            "\n"
            "If module is omitted then class name will be sought in\n"
            "the built-in signals module. Such as in:\n"
            "\n"
            "  - LONGSHORT::name:kwargs or :name\n"
            "\n"
            "If name is omitted, then the 1st signal found in the mod\n"
            "will be used. Such as in:\n"
            "\n"
            "  - module or module:::kwargs"
        ),
    )

    # Observers
    group = parser.add_argument_group(title="Observers and statistics")
    group.add_argument(
        "--observer",
        "-ob",
        dest="observers",
        action="append",
        required=False,
        metavar="module:name:kwargs",
        help=(
            "This option can be specified multiple times.\n"
            "\n"
            "The argument can be specified with the following form:\n"
            "\n"
            "  - module:classname:kwargs\n"
            "\n"
            "    Example: mymod:myclass:a=1,b=2\n"
            "\n"
            "kwargs is optional\n"
            "\n"
            "If module is omitted then class name will be sought in\n"
            "the built-in observers module. Such as in:\n"
            "\n"
            "  - :name:kwargs or :name\n"
            "\n"
            "If name is omitted, then the 1st observer found in the\n"
            "will be used. Such as in:\n"
            "\n"
            "  - module or module::kwargs"
        ),
    )
    # Analyzers
    group = parser.add_argument_group(title="Analyzers")
    group.add_argument(
        "--analyzer",
        "-an",
        dest="analyzers",
        action="append",
        required=False,
        metavar="module:name:kwargs",
        help=(
            "This option can be specified multiple times.\n"
            "\n"
            "The argument can be specified with the following form:\n"
            "\n"
            "  - module:classname:kwargs\n"
            "\n"
            "    Example: mymod:myclass:a=1,b=2\n"
            "\n"
            "kwargs is optional\n"
            "\n"
            "If module is omitted then class name will be sought in\n"
            "the built-in analyzers module. Such as in:\n"
            "\n"
            "  - :name:kwargs or :name\n"
            "\n"
            "If name is omitted, then the 1st analyzer found in the\n"
            "will be used. Such as in:\n"
            "\n"
            "  - module or module::kwargs"
        ),
    )

    # Analyzer - Print
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--pranalyzer",
        "-pralyzer",
        required=False,
        action="store_true",
        help="Automatically print analyzers",
    )

    group.add_argument(
        "--ppranalyzer",
        "-ppralyzer",
        required=False,
        action="store_true",
        help="Automatically PRETTY print analyzers",
    )

    # Indicators
    group = parser.add_argument_group(title="Indicators")
    group.add_argument(
        "--indicator",
        "-ind",
        dest="indicators",
        metavar="module:name:kwargs",
        action="append",
        required=False,
        help=(
            "This option can be specified multiple times.\n"
            "\n"
            "The argument can be specified with the following form:\n"
            "\n"
            "  - module:classname:kwargs\n"
            "\n"
            "    Example: mymod:myclass:a=1,b=2\n"
            "\n"
            "kwargs is optional\n"
            "\n"
            "If module is omitted then class name will be sought in\n"
            "the built-in analyzers module. Such as in:\n"
            "\n"
            "  - :name:kwargs or :name\n"
            "\n"
            "If name is omitted, then the 1st analyzer found in the\n"
            "will be used. Such as in:\n"
            "\n"
            "  - module or module::kwargs"
        ),
    )

    # Writer
    group = parser.add_argument_group(title="Writers")
    group.add_argument(
        "--writer",
        "-wr",
        dest="writers",
        metavar="kwargs",
        nargs="?",
        action="append",
        required=False,
        const="",
        help=(
            "This option can be specified multiple times.\n"
            "\n"
            "The argument can be specified with the following form:\n"
            "\n"
            "  - kwargs\n"
            "\n"
            "    Example: a=1,b=2\n"
            "\n"
            "kwargs is optional\n"
            "\n"
            "It creates a system wide writer which outputs run data\n"
            "\n"
            "Please see the documentation for the available kwargs"
        ),
    )

    # Broker/Commissions
    group = parser.add_argument_group(title="Cash and Commission Scheme Args")
    group.add_argument(
        "--cash", "-cash", required=False, type=float, help="Cash to set to the broker"
    )
    group.add_argument(
        "--commission", "-comm", required=False, type=float, help="Commission value to set"
    )
    group.add_argument("--margin", "-marg", required=False, type=float, help="Margin type to set")
    group.add_argument("--mult", "-mul", required=False, type=float, help="Multiplier to use")

    group.add_argument(
        "--interest",
        required=False,
        type=float,
        default=None,
        help="Credit Interest rate to apply (0.0x)",
    )

    group.add_argument(
        "--interest_long",
        action="store_true",
        required=False,
        default=None,
        help="Apply credit interest to long positions",
    )

    group.add_argument(
        "--slip_perc",
        required=False,
        default=None,
        type=float,
        help="Enable slippage with a percentage value",
    )
    group.add_argument(
        "--slip_fixed",
        required=False,
        default=None,
        type=float,
        help="Enable slippage with a fixed point value",
    )

    group.add_argument(
        "--slip_open",
        required=False,
        action="store_true",
        help="enable slippage for when matching opening prices",
    )

    group.add_argument(
        "--no-slip_match",
        required=False,
        action="store_true",
        help=(
            "Disable slip_match, ie: matching capped at \n"
            "high-low if slippage goes over those limits"
        ),
    )
    group.add_argument(
        "--slip_out",
        required=False,
        action="store_true",
        help="with slip_match enabled, match outside high-low",
    )

    # Output flushing
    group.add_argument(
        "--flush",
        required=False,
        action="store_true",
        help="flush the output - useful under win32 systems",
    )

    # Plot options
    parser.add_argument(
        "--plot",
        "-p",
        nargs="?",
        metavar="kwargs",
        default=False,
        const=True,
        required=False,
        help=(
            "Plot the read data applying any kwargs passed\n"
            "\n"
            "For example:\n"
            "\n"
            '  --plot style="candle" (to plot candlesticks)\n'
        ),
    )

    if pargs:
        return parser.parse_args(pargs)

    return parser.parse_args()


if __name__ == "__main__":
    btrun()

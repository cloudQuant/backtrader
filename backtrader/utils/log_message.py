"""Log Message Module - Logging utilities for backtrader.

This module provides logging functionality using spdlog if available,
with a fallback to simple console logging. It supports daily log file
rotation and configurable output sinks.

Classes:
    SpdLogManager: Manager for creating spdlog-based loggers.
    SimpleLogger: Fallback logger that prints to console.
    DummyLogger: Dummy logger used when spdlog is not available.
    DummySpdLog: Dummy spdlog module for import fallback.

Example:
    >>> log_manager = SpdLogManager(file_name="mylog.log")
    >>> logger = log_manager.create_logger()
    >>> logger.info("Strategy started")
"""

try:
    import spdlog

    SPDLOG_AVAILABLE = True
except ImportError:
    SPDLOG_AVAILABLE = False

    # Create a dummy spdlog module to prevent errors
    class DummySpdLog:
        """Dummy spdlog module for when spdlog is not installed.

        Provides stub implementations of spdlog functions to prevent
        import errors when the spdlog package is not available.
        """

        @staticmethod
        def stdout_sink_st():
            """Create a dummy stdout sink.

            Returns:
                None: Dummy sink implementation.
            """
            return None

        @staticmethod
        def daily_file_sink_st(filename, hour, minute):
            """Create a dummy daily file sink.

            Args:
                filename: Name of the log file.
                hour: Hour for daily rotation.
                minute: Minute for daily rotation.

            Returns:
                None: Dummy sink implementation.
            """
            return None

        @staticmethod
        def SinkLogger(name, sinks):
            """Create a dummy logger.

            Args:
                name: Logger name.
                sinks: List of sinks (ignored).

            Returns:
                DummyLogger: A logger that prints to console.
            """

            class DummyLogger:
                """Fallback logger that prints to console."""

                def info(self, msg):
                    """Log an info message.

                    Args:
                        msg: Message to log.
                    """
                    print(f"[INFO] {msg}")

                def warning(self, msg):
                    """Log a warning message.

                    Args:
                        msg: Message to log.
                    """
                    print(f"[WARNING] {msg}")

                def error(self, msg):
                    """Log an error message.

                    Args:
                        msg: Message to log.
                    """
                    print(f"[ERROR] {msg}")

                def debug(self, msg):
                    """Log a debug message.

                    Args:
                        msg: Message to log.
                    """
                    print(f"[DEBUG] {msg}")

            return DummyLogger()

    spdlog = DummySpdLog()


class SpdLogManager:
    """Manager for creating spdlog-based loggers.

    Creates loggers with daily file rotation. Requires the spdlog
    package to be installed. Falls back to console logging if
    spdlog is unavailable.

    Attributes:
        file_name: Name of the log file.
        logger_name: Name for the logger.
        rotation_hour: Hour of day for log rotation (0-23).
        rotation_minute: Minute of hour for log rotation (0-59).
        print_info: Whether to also print to console.
        spdlog_available: Whether spdlog is installed.
    """

    def __init__(
        self,
        file_name="log_strategy_info.log",
        logger_name="hello",
        rotation_hour=0,
        rotation_minute=0,
        print_info=False,
    ):
        """Initialize the SpdLogManager.

        Args:
            file_name: Name of the output log file.
            logger_name: Name for the logger.
            rotation_hour: Hour (0-23) to rotate log files daily.
            rotation_minute: Minute (0-59) to rotate log files.
            print_info: Whether to also output to console.
        """
        self.file_name = file_name
        self.logger_name = logger_name
        self.rotation_hour = rotation_hour
        self.rotation_minute = rotation_minute
        self.print_info = print_info
        self.spdlog_available = SPDLOG_AVAILABLE

    def create_logger(self):
        """Create a logger instance.

        Returns:
            A logger object (spdlog SinkLogger if available,
            otherwise SimpleLogger).
        """
        if not self.spdlog_available:
            # Return a simple logger that prints to console
            class SimpleLogger:
                """Fallback logger that prints to console."""

                def info(self, msg):
                    """Log an info message.

                    Args:
                        msg: Message to log.
                    """
                    print(f"[INFO] {msg}")

                def warning(self, msg):
                    """Log a warning message.

                    Args:
                        msg: Message to log.
                    """
                    print(f"[WARNING] {msg}")

                def error(self, msg):
                    """Log an error message.

                    Args:
                        msg: Message to log.
                    """
                    print(f"[ERROR] {msg}")

                def debug(self, msg):
                    """Log a debug message.

                    Args:
                        msg: Message to log.
                    """
                    print(f"[DEBUG] {msg}")

            return SimpleLogger()

        if self.print_info:
            sinks = [
                spdlog.stdout_sink_st(),
                # spdlog.stdout_sink_mt(),
                # spdlog.stderr_sink_st(),
                # spdlog.stderr_sink_mt(),
                # spdlog.daily_file_sink_st("DailySinkSt.log", 0, 0),
                # spdlog.daily_file_sink_mt("DailySinkMt.log", 0, 0),
                # spdlog.rotating_file_sink_st("RotSt.log", 1024, 1024),
                # spdlog.rotating_file_sink_mt(self.file_name, 1024, 1024),
                spdlog.daily_file_sink_st(self.file_name, self.rotation_hour, self.rotation_minute),
            ]
        else:
            sinks = [
                spdlog.daily_file_sink_st(self.file_name, self.rotation_hour, self.rotation_minute)
            ]
        logger = spdlog.SinkLogger(self.logger_name, sinks)
        # logger = spdlog.create(self.logger_name, sinks)
        return logger

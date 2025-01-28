import spdlog


class SpdLogManager(object):
    """创建一个spdlog的日志输出功能，每天一个日志文件，使用需要先pip install spdlog
    :param: file_name:输出日志的文件
    :logger_name:输出日志的名称
    :rotation_hour和rotation_minute：用于控制在每天什么时间换新的日志文件
    """

    def __init__(self, file_name="log_strategy_info.log", logger_name="hello", rotation_hour=0, rotation_minute=0,
                 print_info=False):
        self.file_name = file_name
        self.logger_name = logger_name
        self.rotation_hour = rotation_hour
        self.rotation_minute = rotation_minute
        self.print_info = print_info

    def create_logger(self):
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
                spdlog.daily_file_sink_st(self.file_name, self.rotation_hour, self.rotation_minute)
            ]
        else:
            sinks = [spdlog.daily_file_sink_st(self.file_name, self.rotation_hour, self.rotation_minute)]
        logger = spdlog.SinkLogger(self.logger_name, sinks)
        # logger = spdlog.create(self.logger_name, sinks)
        return logger

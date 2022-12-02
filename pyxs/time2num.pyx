from cpython.datetime cimport datetime 

cdef time2num(datetime tm):
    """
    Converts the hour/minute/second/microsecond part of tm (datetime.datetime
    or time) to a num
    """
    cdef double num 
    num = (tm.hour / 24.0 +
           tm.minute / 1440.0 +
           tm.second / 86400.0 +
           tm.microsecond / 86400000000.0)

    return num
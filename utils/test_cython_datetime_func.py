from date import date2num as c_date2num
from date import num2dt as c_num2dt
from date import num2date as c_num2date
from date import time2num as c_time2num
from python_code import date2num as p_date2num
from python_code import num2date as p_num2date
from python_code import num2dt as p_num2dt
from python_code import time2num as p_time2num
# print(dir(p_time2num))
# print(dir(c_time2num))
import datetime 
import time 
def run(n,p_func,c_func):
    d_list = [datetime.datetime.now() for i in range(n)]
    num_list = [c_date2num(i) for i in d_list]
    new_d_list = [c_num2dt(i) for i in num_list]
    # if d_list!=new_d_list:
    #     print(d_list)
    #     print(new_d_list)
    if "2num" in p_func.__name__:
        print("开始时间转化成数字")
        empty_time = run_empty(d_list)
        c_time2num_consume_time = run_cal(c_func,d_list)
        p_time2num_consume_time = run_cal(p_func,d_list)
    else:
        print("开始数字转化成时间")
        empty_time = run_empty(num_list)
        c_time2num_consume_time = run_cal(c_func,num_list)
        p_time2num_consume_time = run_cal(p_func,num_list)
    ct = c_time2num_consume_time-empty_time
    pt = p_time2num_consume_time-empty_time
    print(f"run {n} 次，循环时间为:{empty_time},cython耗费时间为:{ct},python耗费的时间为:{pt},计算部分提升的倍数:{pt/ct}")
    return [empty_time,c_time2num_consume_time,p_time2num_consume_time]

def run_empty(d_list):
    t1 =time.time()
    for d in d_list:
        pass
    t2 = time.time() 
    return t2-t1
def run_cal(func,d_list):
    t1 =time.time()
    for d in d_list:
        func(d)
    t2 = time.time() 
    return t2-t1

if __name__=="__main__":
    print("begin to compare python date2num and cython date2num")
    run(10000000,p_date2num,c_date2num)
    # print("begin to compare python time2num and cython time2num")
    # run(10000000,p_time2num,c_time2num)
    print("begin to compare python num2date and cython num2date")
    run(10000000,p_num2date,c_num2date)
    print("begin to compare python num2dt and cython num2dt")
    run(10000000,p_num2dt,c_num2dt)
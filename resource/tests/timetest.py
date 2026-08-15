#!/bin/python3.13


"""
timetest.py

Prints all available time-related outputs in the current Python environment.
"""



# imports
import time
import datetime
import os



# functions
def showtime():

    print("time.time():", time.time())
    print("time.monotonic():", time.monotonic())
    print("time.perf_counter():", time.perf_counter())
    print("time.process_time():", time.process_time())
    print("time.thread_time():", time.thread_time())
    print("time.gmtime():", time.gmtime())
    print("time.localtime():", time.localtime())
    print("time.ctime():", time.ctime())
    print("time.asctime():", time.asctime())
    print("datetime.datetime.now():", datetime.datetime.now())
    print("datetime.datetime.utcnow():", datetime.datetime.utcnow())
    print("datetime.date.today():", datetime.date.today())

    try:
        print("os.times():", os.times())
    except Exception as e:
        print("os.times() error:", e)



# main
if __name__ == '__main__':
    showtime()

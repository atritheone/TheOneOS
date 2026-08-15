#!/bin/python3.13

import time

print("talker start")

for i in range(50):
    print(f"tick {i}")
    time.sleep(0.2)

print("talker end")
#!/usr/bin/python3


import time
from scapy.all import *

while True:
    time.sleep(2)
    get_stats(client, device_ports)
    print('')

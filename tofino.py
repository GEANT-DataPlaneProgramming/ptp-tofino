#!/bin/python3

# pylint: disable=missing-function-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-module-docstring

import socket
import time

MAX_MSG_SIZE = 8192
ETH_P_ALL = 3

class Socket:
    def __init__(self, skt_name, callback):
        self.skt = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        self.skt.bind((skt_name, ETH_P_ALL))
        self.callback = callback

    def send(self, msg, port_number, get_timestamp=False):
        # pylint: disable=unused-argument
        timestamp = None
        # TODO: Create CPU header and append to message
        self.skt.send(msg)
        if get_timestamp:
            timestamp = time.clock_gettime_ns(time.CLOCK_REALTIME) # TODO: get TS7 from tofino

        return timestamp

    def listen(self):
        while True:
            msg, *_ = self.skt.recvmsg(MAX_MSG_SIZE)
            port_number = 1 # TODO: Get port number from CPU header
            timestamp = time.clock_gettime_ns(time.CLOCK_REALTIME) # TODO: get TS1 from CPU header
            self.callback(msg, port_number, timestamp)

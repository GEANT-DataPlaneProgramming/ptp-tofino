#!/bin/python3

# pylint: disable=invalid-name

import struct
import tofino as driver
from ptp import PTP_PROTO

ETH_P_1588 = 0x88F7
ETH_P_IP = 0x0800
ETH_P_IPV6 = 0x86DD

MULTICAST_ADDR = {
    PTP_PROTO.ETHERNET: 0x011b19000000.to_bytes(6, 'big'),
    PTP_PROTO.UDP_IPV4: {},
    PTP_PROTO.UDP_IPV6: {}
}

MULTICAST_P2P_ADDR = {
    PTP_PROTO.ETHERNET: 0x0180c200000e.to_bytes(6, 'big'),
    PTP_PROTO.UDP_IPV4: {},
    PTP_PROTO.UDP_IPV6: {}
}

class Ethernet:
    parser = struct.Struct('!6s6sH')

    def __init__(self, buffer=b''):
        self.src = None
        self.dst = None
        self.type = None
        if buffer: self.parse(buffer)

    def parse(self, buffer):
        t = self.parser.unpack(buffer[:self.parser.size])
        self.dst = t[0]
        self.src = t[1]
        self.type = t[2]

    def bytes(self):
        t = (self.dst, self.src, self.type)
        return self.parser.pack(*t)

class UDP:
    parser = struct.Struct('!4H')

    def __init__(self):
        self.src = None
        self.dst = None
        self.len = None
        self.chk = 0

    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.src = t[0]
        self.dst = t[1]
        self.len = t[2]
        self.chk = t[3]

    def bytes(self):
        t = (self.src, self.dst, self.len, self.chk)
        return self.parser.pack(*t)

class IPv4:
    parser = struct.Struct('!2B3H2BH4s4s')

    def __init__(self):
        self.version = 4
        self.ihl = 5
        self.tos = 0
        self.len = None
        self.id = 0
        self.flags = 0
        self.fragment_offset = 0
        self.ttl = None
        self.proto = None
        self.checksum = None
        self.src = None
        self.dst = None

    def parse(self, buffer):
        pass

    def bytes(self):
        pass

class IPv6:
    parser = struct.Struct('!LHBB16s16s')

    def __init__(self):
        self.version = 6
        self.traffic_class = 0
        self.flow_label = 0
        self.payload_len = None
        self.next_header = None
        self.hop_limit = None
        self.src = None
        self.dst = None

    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.version = (t[0] >> 28) & 0x0F
        self.traffic_class = (t[0] >> 20) & 0xFF
        self.flow_label = t[0] & 0x000FFFFF
        self.payload_len = t[1]
        self.next_header = t[2]
        self.hop_limit = t[3]
        self.src = t[4]
        self.dst = t[5]

    def bytes(self):
        t = (
            (self.version << 28) & (self.traffic_class << 20) & self.flow_label,
            self.payload_len,
            self.next_header,
            self.hop_limit,
            self.src,
            self.dst
        )
        return self.parser.pack(*t)

class Socket:
    def __init__(self, skt_name, callback):
        # TODO: Set source addresses
        self.eth_addr = b'\x00' * 6
        self.ip4_addr = b'\x00' * 4
        self.ip6_addr = b'\x00' * 16
        self.skt = driver.Socket(skt_name, self.recv_message)
        self.callback = callback

    def send_message(self, msg, transport, port_number, get_timestamp=False):
        hdr = None
        timestamp = None

        if transport == PTP_PROTO.ETHERNET:
            hdr = self._get_ethernet_header()

        if hdr:
            timestamp = self.skt.send(hdr.bytes() + msg, port_number, get_timestamp)

        return timestamp


    def recv_message(self, msg, port_number, timestamp):
        ethernet = Ethernet(msg)
        if ethernet.type == ETH_P_1588:
            self.callback(msg[Ethernet.parser.size:], port_number, timestamp)

    def _get_ethernet_header(self):
        hdr = Ethernet()
        hdr.src = self.eth_addr
        # TODO: select destination based on message type
        hdr.dst = MULTICAST_ADDR[PTP_PROTO.ETHERNET]
        hdr.type = ETH_P_1588
        return hdr

    async def listen(self):
        await self.skt.listen()

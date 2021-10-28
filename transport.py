#!/bin/python3

import ptp, struct, socket

ETH_P_ALL = 3
ETH_P_1588 = 0x88F7
ETH_P_IP = 0x0800
ETH_P_IPV6 = 0x86DD

class Ethernet:
    parser = struct.Struct('!6s6sH')

    def __init__(self):
        self.src = None
        self.dst = None
        self.type = None

    def parse(self, buffer):
        t = self.parser.unpack(buffer)
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
        self.dst = t[5]

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
    def __init__(self, skt_name):

        # self.interface = interface # FIX: don't think i need this
        # FIX: Addresses may be per port
        self.eth_addr = b'\x00' * 6
        self.ip4_addr = b'\x00' * 4
        self.ip6_addr = b'\x00' * 16
        #self.skt = self._unix_socket(skt_name)
        self.skt = self._packet_socket(skt_name)

    # def _unix_socket(self, path):
    #     skt = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM, 0)
    #     skt.bind(path)
    #     return skt

    def _packet_socket(self, interface):
        skt = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        skt.bind((interface, ETH_P_ALL))
        return skt

    def _unix_socket(self):
        pass

    def sendMessage(self, msg, transport, portNumber, destinationAddress):
        cpu = b'' # FIX: Construct CPU Header
        if transport == ptp.PTP_PROTO.ETHERNET:
            self._sendEthernet(cpu, msg, destinationAddress)

    def _sendEthernet(self, cpu, msg, destinationAddress):
        hdr = Ethernet()
        hdr.src = self.eth_addr
        hdr.dst = destinationAddress
        hdr.type = ETH_P_1588
        self.skt.send(cpu + hdr.bytes() + msg)

    def recvmsg(self):
        MAX_MSG_SIZE = 8192
        return self.skt.recvmsg(MAX_MSG_SIZE)

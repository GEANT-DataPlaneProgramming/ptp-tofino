#!/usr/bin/python3

import struct
#import sys
#from scapy.all import *

INTERFACE = 'ens1'
PTP_ETHERTYPE = 0x88f7

def send_sync(dest):
    header = bytearray(b'\x00' * 34)
    header[0] = 0
    message = bytearray(b'\x00' * 8)

def send_delay_req(dest):
    header = bytearray(b'\x00' * 34)
    header[0] = 1
    message = bytearray(b'\x00' * 8)

def send_delay_resp(dest):
    header = bytearray(b'\x00' * 34)
    header[0] = 9
    message = bytearray(b'\x00' * 8)

def send_follow_up(dest):
    header = bytearray(b'\x00' * 34)
    header[0] = 8
    message = bytearray(b'\x00' * 8)

def get_tofino_ts7():
    pass

def parse_ethernet(pkt_bytes):
    pkt = {}
    pkt['dst_addr'] = struct.unpack("!Q", b'\x00\x00' + pkt_bytes[0:6])
    pkt['src_addr'] = struct.unpack("!Q", b'\x00\x00' + pkt_bytes[6:12])
    pkt['Ethertype'] = struct.unpack("!Q", b'\x00\x00' + pkt_bytes[12:13])
    if pkt['Ethertype'] == PTP_ETHERTYPE: parse_ptp_common_pkt(pkt, pkt_bytes)

def parse_ptp_common_pkt(pkt, pkt_bytes):
    pkt['Ethertype'] = struct.unpack("!Q", b'\x00\x00' + pkt_bytes[12:13])
    pkt['transportSpecific'] = pkt_bytes[0] >> 4
    pkt['messageType'] = pkt_bytes[0] & 0x0f
    # 4 bits reserved [1] >> 4
    pkt['versionPTP'] = pkt_bytes[1] & 0x0f
    pkt['messageLength'] = struct.unpack("!H", pkt_bytes[2:4])
    pkt['domainNumber'] = pkt_bytes[4]
    # 1 Byte reserved [5]
    pkt['flagField'] = struct.unpack("!H", pkt_bytes[6:8]) # TODO: Expand
    pkt['correctionField'] = struct.unpack("!Q", pkt_bytes[8:16])
    # 4 Bytes reserved [16:20]
    pkt['sourcePortIdentity_clockIdentity'] = pkt_bytes[20:28] # NaN
    pkt['sourcePortIdentity_portNumber'] = struct.unpack("!H", pkt_bytes[28:30])
    pkt['sequenceId'] = struct.unpack("!H", pkt_bytes[30:32])
    pkt['controlField'] = pkt_bytes[32]
    pkt['logMessageInterval'] = pkt_bytes[33]

    match pkt['messageType']: # Does this even work?
        case 0x0: # Sync
        case 0x1: # Delay_Req
            pkt['originTimestamp_seconds'] = struct.unpack("!Q", b'\x00\x00' + pkt_bytes[34:40])
            pkt['originTimestamp_nanoseconds'] = struct.unpack("!L", pkt_bytes[40:44])
        case 0x8: # Follow_Up
            pkt['preciseOriginTimestamp_seconds'] = struct.unpack("!Q", b'\x00\x00' + pkt_bytes[34:40])
            pkt['preciseOriginTimestamp_nanoseconds'] = struct.unpack("!L", pkt_bytes[40:44])
        case 0x9: # Delay_Resp
            pkt['receiveTimestamp_seconds'] = struct.unpack("!Q", b'\x00\x00' + pkt_bytes[34:40])
            pkt['receiveTimestamp_nanoseconds'] = struct.unpack("!L", pkt_bytes[40:44])
            pkt['requestingPortIdentity_clockIdentity'] = pkt_bytes[44:52] # NaN
            pkt['requestingPortIdentity_portNumber'] = struct.unpack("!H", pkt_bytes[52:54])

sniff(iface=INTERFACE, count=1000, prn=lambda x: parse_ethernet(x))

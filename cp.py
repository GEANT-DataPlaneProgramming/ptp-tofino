#!/bin/python3

# pylint: disable=invalid-name

from copy import copy
from optparse import OptionParser
import threading
import random
import ptp
import ptp_transport
from ptp_datasets import *

## Custom Classes ##

# Impements Section 7.3.7
class SequenceTracker:
    def __init__(self):
        self.sequenceId = {}

    def getSequenceId(self, portNumber, messageType, destination):
        key = (portNumber, messageType, destination)
        if key not in self.sequenceId:
            self.sequenceId[key] = 0
        sequenceId = self.sequenceId[key]
        self.sequenceId[key] = (sequenceId + 1) & 0xFFFF
        return sequenceId

class Timer:
    def __init__(self, interval, function, args):
        self.i = interval
        self.f = function
        self.args = args
        self.t = None

    def _run(self, args):
        self.start()
        self.f(args)

    def start(self):
        self.t = threading.Timer(self.i, self._run, self.args)
        self.t.start()

    def stop(self):
        if self.t: self.t.cancel()

    def reset(self):
        self.stop()
        self.start()

class Port:
    def __init__(self, profile, clock, portNumber):
        self.portDS = PortDS(profile, clock.defaultDS.clockIdentity, portNumber)
        self.foreignMasterList = ForeignMasterList()
        self.transport = ptp.PTP_PROTO.ETHERNET # FIX: make configurable

        announceInterval = 2 ** self.portDS.logAnnounceInterval
        syncInterval = 2 ** self.portDS.logSyncInterval
        announceReceiptTimeoutInterval = self.portDS.announceReceiptTimeout * announceInterval
        announceReceiptTimeoutInterval += (announceInterval * random.random())

        self.announeTimer = Timer(announceInterval, clock.sendAnnounce, [portNumber])
        self.syncTimer = Timer(syncInterval, clock.sendSync, [portNumber])
        self.announceReceiptTimeoutTimer = Timer(announceReceiptTimeoutInterval, clock.announceReceiptTimeoutEvent, [portNumber])

class OrdinaryClock:
    def __init__(self, PTP_PROFILE, clockIdentity, numberPorts, interface):
        print("[INFO] Clock ID: %s" % (clockIdentity.hex()))
        print("[EVENT] POWERUP (All Ports)")
        print("[STATE] INITIALIZING (All Ports)")
        self.defaultDS = DefaultDS(PTP_PROFILE, clockIdentity, numberPorts)
        self.currentDS = CurrentDS()
        self.parentDS = ParentDS(self.defaultDS)
        self.timePropertiesDS = TimePropertiesDS()
        self.portList = {}
        for i in range(numberPorts):
            self.portList[i+1] = Port(PTP_PROFILE, self, i + 1)
        self.sequenceTracker = SequenceTracker() # FIX: per port(?)
        self.skt = ptp_transport.Socket(interface)
        self.listeningTransition()
        self.skt.listen(self.packetHandler) # FIX: should this be before transition

    def packetHandler(self, buffer):
        CPU_HDR_SIZE = 0
        ETH_HDR_SIZE = 14

        # cpu = tofino.CPU(buffer[:CPU_HDR_SIZE]) # FIX: implement CPU header
        buffer = buffer[CPU_HDR_SIZE:]
        metadata = {'portNumber': 1} # FIX: get port number from CPU header

        eth = ptp_transport.Ethernet()
        eth.parse(buffer[:ETH_HDR_SIZE])
        buffer = buffer[ETH_HDR_SIZE:]

        if eth.type == ptp_transport.ETH_P_1588:
            self.recvMessage(buffer, metadata)
        elif eth.type == ptp_transport.ETH_P_IP:
            pass # FIX: parseIPv4_UDP(), maybe recv
        elif eth.type == ptp_transport.ETH_P_IPV6:
            pass # FIX: parseIPv6_UDP(), maybe recv

    def recvMessage(self, buffer, metadata):
        hdr = ptp.Header(buffer)
        portNumber = metadata['portNumber']
        # Check if message is from the same clock
        if hdr.sourcePortIdentity.clockIdentity == self.defaultDS.clockIdentity:
            if hdr.sourcePortIdentity == self.portList[portNumber].portDS.sourcePortIdentity:
                print("[WARN] Message received by sending port (%d)" % (portNumber))
            else:
                print("[WARN] Message received by sending clock (%d)" % (portNumber))
                # FIX: put all but lowest numbered port in PASSIVE state
        else:
            if hdr.messageType == ptp.PTP_MESG_TYPE.ANNOUNCE:
                self.recvAnnounce(ptp.Announce(buffer), portNumber)
            # FIX: Handle other message types

    ## Transitions ##

    def listeningTransition(self):
        print("[STATE] LISTENING (All Ports)")
        for port in self.portList.values():
            port.portDS.portState = ptp.PTP_STATE.LISTENING
            port.announceReceiptTimeoutTimer.start()

    def masterTransition(self, portNumber):
        print("[STATE] (%d) MASTER" % (portNumber))
        port = self.portList[portNumber]
        port.announceReceiptTimeoutTimer.stop()
        port.announeTimer.start()
        port.syncTimer.start()
        port.portDS.portState = ptp.PTP_STATE.MASTER
        self.sendAnnounce(portNumber)
        self.sendSync(portNumber)

    ## Updates ##

    def updateM1M2(self, portNumber):
        print("[STATE] (%d) Decision code M1/M2" % (portNumber))
        self.currentDS.stepsRemoved = 0
        self.currentDS.offsetFromMaster = 0
        self.currentDS.meanPathDelay = 0
        self.parentDS.parentPortIdentity.clockIdentity = self.defaultDS.clockIdentity
        self.parentDS.parentPortIdentity.portNumber = 0
        self.parentDS.grandmasterIdentity = self.defaultDS.clockIdentity
        self.parentDS.grandmasterClockQuality = self.defaultDS.clockQuality
        self.parentDS.grandmasterPriority1 = self.defaultDS.priority1
        self.parentDS.grandmasterPriority2 = self.defaultDS.priority2
        self.timePropertiesDS.currentUtcOffset = 37
        self.timePropertiesDS.currentUtcOffsetValid = False
        self.timePropertiesDS.leap59 = False
        self.timePropertiesDS.leap61 = False
        self.timePropertiesDS.timeTraceable = False
        self.timePropertiesDS.frequencyTraceable = False
        self.timePropertiesDS.ptpTimescale = False
        self.timePropertiesDS.timeSource = ptp.PTP_TIME_SRC.INTERNAL_OSCILLATOR

    def updateM3(self, portNumber):
        print("[STATE] (%d) Decision code M3" % (portNumber))

    def updateP1P2(self, portNumber):
        print("[STATE] (%d) Decision code P1/P2" % (portNumber))

    def updateS1(self, msg):
        print("[STATE] Decision code S1")
        self.currentDS.stepsRemoved = msg.stepsRemoved + 1
        self.parentDS.parentPortIdentity = copy(msg.sourcePortIdentity)
        self.parentDS.grandmasterIdentity = msg.grandmasterIdentity
        self.parentDS.grandmasterClockQuality = copy(msg.grandmasterClockQuality)
        self.parentDS.grandmasterPriority1 = msg.grandmasterPriority1
        self.parentDS.grandmasterPriority2 = msg.grandmasterPriority2
        self.timePropertiesDS.currentUtcOffset = msg.currentUtcOffset
        self.timePropertiesDS.currentUtcOffsetValid = msg.flagField.currentUtcOffsetValid
        self.timePropertiesDS.leap59 = msg.flagField.leap59
        self.timePropertiesDS.leap61 = msg.flagField.leap61
        self.timePropertiesDS.timeTraceable = msg.flagField.timeTraceable
        self.timePropertiesDS.frequencyTraceable = msg.flagField.frequencyTraceable
        self.timePropertiesDS.ptpTimescale = msg.flagField.ptpTimescale
        self.timePropertiesDS.timeSource = msg.timeSource

    ## Events ##

    def powerupEvent(self):
        pass

    def initializeEvent(self):
        pass

    def decisionEvent(self):
        pass

    def recommendedStateEvent(self):
        pass

    def announceReceiptTimeoutEvent(self, portNumber):
        print("[EVENT] ANNOUNCE_RECEIPT_TIMEOUT_EXPIRES (Port %d)" % (portNumber))
        valid_states = (ptp.PTP_STATE.LISTENING, ptp.PTP_STATE.UNCALIBRATED, ptp.PTP_STATE.SLAVE, ptp.PTP_STATE.PASSIVE)
        peer_ports = [self.portList[index] for index in self.portList if index != portNumber]

        if self.portList[portNumber].portDS.portState in valid_states:
            if ptp.PTP_STATE.SLAVE in [port.portDS.portState for port in peer_ports]:
                self.updateM3(portNumber)
            else:
                self.updateM1M2(portNumber)
            self.masterTransition(portNumber)
        else:
            print("[WARN] UNEXPECTED CONDITION")

    def qualificationTimeoutEvent(self, port):
        pass

    def masterSelectedEvent(self, port):
        pass

    ## Send Messages ##

    def sendAnnounce(self, portNumber, destinationAddress=b''):
        print("[SEND] ANNOUNCE (Port %d)" % (portNumber))
        pDS = self.portList[portNumber].portDS
        transport = self.portList[portNumber].transport
        msg = ptp.Announce()

        msg.transportSpecific = ptp.CONST[transport]['transportSpecific']
        msg.messageType = ptp.PTP_MESG_TYPE.ANNOUNCE
        msg.versionPTP = pDS.versionNumber
        msg.messageLength = ptp.Header.parser.size + ptp.Announce.parser.size
        msg.domainNumber = self.defaultDS.domainNumber
        if pDS.portState == ptp.PTP_STATE.MASTER:
            msg.flagField.alternateMasterFlag = False
        else:
            print("[WARN] Alternate Master not Implemented")
        msg.flagField.unicastFlag = destinationAddress != b''
        msg.flagField.profile1 = False
        msg.flagField.profile2 = False
        msg.flagField.leap61 = self.timePropertiesDS.leap61
        msg.flagField.leap59 = self.timePropertiesDS.leap59
        msg.flagField.currentUtcOffsetValid = self.timePropertiesDS.currentUtcOffsetValid
        msg.flagField.ptpTimescale = self.timePropertiesDS.ptpTimescale
        msg.flagField.timeTraceable = self.timePropertiesDS.timeTraceable
        msg.flagField.frequencyTraceable = self.timePropertiesDS.frequencyTraceable
        msg.correctionField = 0
        msg.sourcePortIdentity = copy(pDS.portIdentity)
        msg.sequenceId = self.sequenceTracker.getSequenceId(portNumber, ptp.PTP_MESG_TYPE.ANNOUNCE, destinationAddress)
        msg.controlField = 0x05
        msg.logMessageInterval = pDS.logAnnounceInterval

        msg.originTimestamp.secondsField = 0 # UInt48
        msg.originTimestamp.nanosecondsField = 0 # UInt32
        msg.currentUtcOffset = self.timePropertiesDS.currentUtcOffset # Int16
        msg.grandmasterPriority1 = self.parentDS.grandmasterPriority1 # UInt8
        msg.grandmasterClockQuality = copy(self.parentDS.grandmasterClockQuality)
        msg.grandmasterPriority2 = self.parentDS.grandmasterPriority1 # UInt8
        msg.grandmasterIdentity = self.parentDS.grandmasterIdentity # Octet[8]
        msg.stepsRemoved = self.currentDS.stepsRemoved # UInt16
        msg.timeSource = self.timePropertiesDS.timeSource # Enum8

        if destinationAddress == b'':
            destinationAddress = ptp.CONST[transport]['destinationAddress']
        self.skt.sendMessage(msg.bytes(), transport, portNumber, destinationAddress)

    def sendSync(self, portNumber):
        print("[SEND] SYNC (Port %d)" % (portNumber))
        msg = ptp.Sync()

    ## Recv Messages ##

    def recvAnnounce(self, msg, portNumber):
        print("[RECV] Announce (Port %d)" % (portNumber))
        pDS = self.portList[portNumber].portDS
        if pDS.portState in (ptp.PTP_STATE.INITIALIZING, ptp.PTP_STATE.DISABLED, ptp.PTP_STATE.FAULTY):
            print("[RECV] (%d) Ignoring Announce due to state" % (portNumber))
        elif pDS.portState == ptp.PTP_STATE.SLAVE and self.parentDS.parentPortIdentity == msg.sourcePortIdentity:
            print("[RECV] (%d) Received Announce from Master" % (portNumber))
            self.updateS1(msg)
        else:
            print("[RECV] (%d) Updating ForeignMasterList" % (portNumber))
            self.portList[portNumber].foreignMasterList.update(msg, pDS)

class TransparentClock:
    class Port:
        def __init__(self, profile, clock, portNumber):
            self.transparentClockPortDS = TransparentClockPortDS(profile, clock.defaultDS.clockIdentity, portNumber)
            self.transport = ptp.PTP_PROTO.ETHERNET # FIX: make configurable

    def __init__(self, profile, clockIdentity, numberPorts):
        self.transparentClockDefaultDS = TransparentClockDefaultDS(profile, clockIdentity, numberPorts)
        self.portList = {}
        for i in range(numberPorts):
            self.portList[i+1] = self.Port(profile, self, i + 1)

### Main ###

randomClockIdentity = random.randrange(2**64).to_bytes(8, 'big') # FIX: get from interface

parser = OptionParser()
# FIX: Add option for providing clockIdentity (as MAC and/or IPv6?)
# parser.add_option("-d", "--identity", action="callback", type="string", callback=formatIdentity, default=randomClockIdentity)
parser.add_option("-n", "--ports", type="int", dest="numberPorts", default=1)
parser.add_option("-i", "--interface", dest="interface", default='veth1')

(options, _) = parser.parse_args()

c = OrdinaryClock(ptp.PTP_PROFILE_E2E, randomClockIdentity, options.numberPorts, options.interface)

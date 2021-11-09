#!/bin/python3

# pylint: disable=invalid-name
# pylint: disable=missing-function-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-module-docstring
# pylint: disable=line-too-long
# pylint: disable=too-few-public-methods
# pylint: disable=too-many-instance-attributes
# pylint: disable=multiple-statements

from copy import copy
from optparse import OptionParser
import threading
import random
import time
import ptp
import ptp_transport
from ptp_datasets import DefaultDS, CurrentDS, ParentDS, TimePropertiesDS, PortDS, ForeignMasterDS
from ptp_datasets import TransparentClockDefaultDS, TransparentClockPortDS, BMC_Entry
from ptp import PTP_STATE

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
    def __init__(self, interval, function, *args):
        self.i = interval
        self.f = function
        self.args = args
        self.t = None

    def run(self):
        self.start()
        self.f(*self.args)

    def start(self, interval=None):
        if interval: self.i = interval
        self.stop()
        self.t = threading.Timer(self.i, self.run)
        self.t.start()

    def stop(self):
        if self.t: self.t.cancel()

    def reset(self):
        self.start()

class Port:
    def __init__(self, profile, clock, portNumber):
        self.clock = clock
        self.state_decision_code = None
        self.master_changed = False
        self.next_state = None
        self.portDS = PortDS(profile, clock.defaultDS.clockIdentity, portNumber)
        self.e_rbest = None
        self.foreignMasterList = set()
        self.transport = ptp.PTP_PROTO.ETHERNET # FIX: make configurable

        announceInterval = 2 ** self.portDS.logAnnounceInterval
        syncInterval = 2 ** self.portDS.logSyncInterval
        announceReceiptTimeoutInterval = self.portDS.announceReceiptTimeout * announceInterval
        announceReceiptTimeoutInterval += (announceInterval * random.random())

        self.qualificationTimeoutTimer = Timer(0, self.qualificationTimeoutEvent)
        self.announeTimer = Timer(announceInterval, clock.sendAnnounce, portNumber)
        self.syncTimer = Timer(syncInterval, clock.sendSync, portNumber)
        self.announceReceiptTimeoutTimer = Timer(announceReceiptTimeoutInterval, self.announceReceiptTimeoutEvent)

    def updateForeignMasterList(self, msg):
        for fmDS in self.foreignMasterList:
            if fmDS.foreignMasterPortIdentity == msg.sourcePortIdentity:
                fmDS.update(msg, self.portDS)
                break
        else:
            self.foreignMasterList.add(ForeignMasterDS(msg, self.portDS))

    def calc_e_rbest(self):
        # FIX: Remove master from foreignMasterList(?)
        print("[BMC] (%d) Calculating E rbest" % (self.portDS.portIdentity.portNumber))
        announceInterval = 2 ** self.portDS.logAnnounceInterval
        ts_threshold = time.monotonic() - (4 * announceInterval)
        qualified = [
            fmDS.entry for fmDS in self.foreignMasterList
            if len([ts for ts in fmDS.timestamps if ts > ts_threshold]) == 2
            and fmDS.entry.steps_removed < 255
        ]
        if self.portDS.portState == ptp.PTP_STATE.SLAVE and self.e_rbest and self.e_rbest not in qualified:
            qualified.append(self.e_rbest)

        e_rbest = None if len(qualified) == 0 else qualified[0]
        for i in range(1, len(qualified)):
            e_rbest = e_rbest if e_rbest.compare(qualified[i]) < 0 else qualified[i]

        if e_rbest: qualified.remove(e_rbest)
        for fmDS in self.foreignMasterList:
            if fmDS.entry in qualified: self.foreignMasterList.remove(fmDS)

        self.e_rbest = e_rbest

    def changeState(self, state=None):
        portNumber = self.portDS.portIdentity.portNumber

        if state:
            self.next_state = state

        if self.next_state != PTP_STATE.MASTER:
            self.announeTimer.stop()
            self.syncTimer.stop()

        # 9.2.6.11
        if self.next_state in (PTP_STATE.INITIALIZING, PTP_STATE.PRE_MASTER, PTP_STATE.FAULTY, PTP_STATE.DISABLED, PTP_STATE.MASTER):
            self.announceReceiptTimeoutTimer.stop()

        # State Change
        if self.next_state:
            print("[STATE] (%d) New State %d" % (portNumber, self.next_state))
            self.portDS.portState = self.next_state

        # 9.2.6.11
        if self.next_state in (PTP_STATE.LISTENING, PTP_STATE.UNCALIBRATED, PTP_STATE.SLAVE, PTP_STATE.PASSIVE):
            self.announceReceiptTimeoutTimer.start()

        if self.next_state == PTP_STATE.MASTER:
            self.announeTimer.run()
            self.syncTimer.run()

        # 9.2.6.10
        if self.next_state == PTP_STATE.PRE_MASTER:
            if self.state_decision_code in ("M1", "M2"):
                self.qualificationTimeoutEvent()
            else: # Assuming State Decision Code M3
                announceInterval = 2 ** self.portDS.logAnnounceInterval
                n = self.clock.currentDS.stepsRemoved + 1
                qualificationTimeoutInterval = n * announceInterval
                self.qualificationTimeoutTimer.start(qualificationTimeoutInterval)

        self.next_state = None

    ## Events ##

    def recommendedStateEvent(self):
        """State Machine (9.2.5 & Fig 23) Changes based on Recommended State Event"""
        # Get next state based on recommended state

        portNumber = self.portDS.portIdentity.portNumber
        state = self.portDS.portState
        self.next_state = None

        valid_states = (
            PTP_STATE.LISTENING,
            PTP_STATE.UNCALIBRATED,
            PTP_STATE.SLAVE,
            PTP_STATE.PRE_MASTER,
            PTP_STATE.MASTER,
            PTP_STATE.PASSIVE
        )

        if state in valid_states:
            if self.state_decision_code in ("M1", "M2", "M3"):
                print("[EVENT] (%d) Recommended State = BMC_MASTER " % (portNumber))
                if state != PTP_STATE.MASTER:
                    self.next_state = PTP_STATE.PRE_MASTER
                else:
                    self.next_state = PTP_STATE.MASTER
            elif self.state_decision_code in ("P1", "MP2"):
                print("[EVENT] (%d) Recommended State = BMC_PASSIVE " % (portNumber))
                self.next_state = PTP_STATE.PASSIVE
            elif self.state_decision_code == "S1":
                print("[EVENT] (%d) Recommended State = BMC_SLAVE " % (portNumber))
                if state == PTP_STATE.SLAVE and not self.master_changed:
                    self.next_state = PTP_STATE.SLAVE
                else:
                    self.next_state = PTP_STATE.UNCALIBRATED
            else:
                print("[INFO] (%d) No Recommended State" % (portNumber))
        else:
            print("[INFO] (%d) Ignoring Recommended State Due to Current State" % (portNumber))

    def masterClockSelectedEvent(self):
        portNumber = self.portDS.portIdentity.portNumber
        print("[EVENT] (%d) MASTER_CLOCK_SELECTED " % (portNumber))
        if self.portDS.portState == ptp.PTP_STATE.UNCALIBRATED:
            self.changeState(ptp.PTP_STATE.SLAVE)

    def qualificationTimeoutEvent(self):
        self.qualificationTimeoutTimer.stop()
        portNumber = self.portDS.portIdentity.portNumber
        print("[EVENT] (%d) QUALIFICATION_TIMEOUT_EXPIRES " % (portNumber))
        if self.portDS.portState == ptp.PTP_STATE.PRE_MASTER:
            self.changeState(ptp.PTP_STATE.MASTER)

    def announceReceiptTimeoutEvent(self):
        portNumber = self.portDS.portIdentity.portNumber
        print("[EVENT] (%d) ANNOUNCE_RECEIPT_TIMEOUT_EXPIRES" % (portNumber))
        valid_states = (PTP_STATE.LISTENING, PTP_STATE.UNCALIBRATED, PTP_STATE.SLAVE, PTP_STATE.PASSIVE)
        peer_ports = {port for port in self.clock.portList.values() if port is not self}

        if self.portDS.portState in valid_states:
            if PTP_STATE.SLAVE in [port.portDS.portState for port in peer_ports]:
                self.clock.updateM3(portNumber)
            else:
                self.clock.updateM1M2(portNumber)
            self.changeState(PTP_STATE.MASTER)
        else:
            print("[WARN] UNEXPECTED CONDITION")


class OrdinaryClock:
    def __init__(self, profile, clockIdentity, numberPorts, interface):
        print("[INFO] Clock ID: %s" % (clockIdentity.hex()))
        print("[EVENT] POWERUP (All Ports)")
        print("[STATE] INITIALIZING (All Ports)")
        self.defaultDS = DefaultDS(profile, clockIdentity, numberPorts)
        self.currentDS = CurrentDS()
        self.parentDS = ParentDS(self.defaultDS)
        self.timePropertiesDS = TimePropertiesDS()
        self.portList = {}
        announceInterval = 2 ** profile['portDS.logAnnounceInterval']
        self.state_decision_event_timer = Timer(announceInterval, self.stateDecisionEvent)
        self.state_decision_event_timer.start()
        for i in range(numberPorts):
            self.portList[i+1] = Port(profile, self, i + 1)
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



    ## BMC ##

    def get_e_best(self):
        n_e_rbest = [port.e_rbest for port in self.portList.values() if port.e_rbest]
        e_best = None if len(n_e_rbest) == 0 else n_e_rbest[0]
        for i in range(1, len(n_e_rbest)):
            if e_best.compare(n_e_rbest[i]) > 0: e_best = n_e_rbest[i]
        return e_best

    def state_decision_algorithm(self, e_best, port):
        """State Decision Algorithm 9.3.3 & Figure 26"""
        d0 = BMC_Entry(self.defaultDS)

        if port.e_rbest is None and port.portDS.portState == ptp.PTP_STATE.LISTENING:
            return None # Remain in LISTENING state
        elif self.defaultDS.clockQuality.clockClass < 128:
            if d0.compare(port.e_rbest) < 0:
                return "M1"
            else:
                return "P1"
        elif d0.compare(port.e_rbest) < 0:
            return "M2"
        elif e_best is port.e_rbest:
            return "S1"
        elif e_best.compare(port.e_rbest) == -1:
            return "P2"
        else:
            if e_best.compare(port.e_rbest) == -2: print("[WARN] Possible issue with SDA")
            return "M3"

    ## Transitions ##

    def listeningTransition(self):
        print("[STATE] LISTENING (All Ports)")
        for port in self.portList.values():
            port.changeState(ptp.PTP_STATE.LISTENING)

    ## Data Set Updates ##

    def updateM1M2(self, portNumber):
        print("[INFO] Update for Decision code M1/M2")
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
        # pylint: disable=no-self-use
        print("[INFO] Update for Decision code M3")

    def updateP1P2(self, portNumber):
        # pylint: disable=no-self-use
        print("[INFO] Update for Decision code P1/P2")

    def updateS1(self, msg):
        print("[INFO] Update for Decision code S1")
        master_changed = self.parentDS.parentPortIdentity != msg.sourcePortIdentity
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
        return master_changed

    ## Events ##

    def powerupEvent(self):
        pass

    def initializeEvent(self):
        pass

    def stateDecisionEvent(self):
        """STATE_DECISION_EVENT 9.2.6.8"""
        print("[EVENT] STATE_DECISION_EVENT (All Ports)")
        # FIX: Abort if any port is in INITIALIZING state
        for port in self.portList.values():
            port.calc_e_rbest()
        e_best = self.get_e_best()

        for port in self.portList.values():
            port.state_decision_code = self.state_decision_algorithm(e_best, port)

        for port in self.portList.values():
            if port.state_decision_code in ("M1", "M2"):
                self.updateM1M2(port.portDS.portIdentity.portNumber)
            elif port.state_decision_code == "M3":
                self.updateM3(port.portDS.portIdentity.portNumber)
            elif port.state_decision_code in ("P1", "P2"):
                self.updateP1P2(port.portDS.portIdentity.portNumber)
            elif port.state_decision_code == "S1":
                port.master_changed = self.updateS1(e_best.msg)
            else:
                print("[WARN] (%d) No Update Performed" % (port.portDS.portIdentity.portNumber))

        for port in self.portList.values():
            port.recommendedStateEvent()

        for port in self.portList.values():
            port.changeState()

    def masterSelectedEvent(self, port):
        pass

    ## Send Messages ##

    def sendAnnounce(self, portNumber, destinationAddress=b''):
        print("[SEND] ANNOUNCE (Port %d)" % (portNumber))
        # TODO: ensure port is in proper state
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

    def sendSync(self, portNumber, destinationAddress=b''):
        port = self.portList[portNumber]
        if port.portDS.portState == PTP_STATE.MASTER:
            print("[SEND] SYNC (Port %d)" % (portNumber))
            pDS = self.portList[portNumber].portDS
            transport = self.portList[portNumber].transport
            msg = ptp.Sync()

            msg.transportSpecific = ptp.CONST[transport]['transportSpecific']
            msg.messageType = ptp.PTP_MESG_TYPE.SYNC
            msg.versionPTP = pDS.versionNumber
            msg.messageLength = ptp.Header.parser.size + ptp.Sync.parser.size
            msg.domainNumber = self.defaultDS.domainNumber
            if pDS.portState == ptp.PTP_STATE.MASTER:
                msg.flagField.alternateMasterFlag = False
            else:
                print("[WARN] Alternate Master not Implemented")
            msg.flagField.twoStepFlag = self.defaultDS.twoStepFlag
            msg.flagField.unicastFlag = destinationAddress != b''
            msg.flagField.profile1 = False
            msg.flagField.profile2 = False
            msg.correctionField = 0
            msg.sourcePortIdentity = copy(pDS.portIdentity)
            msg.sequenceId = self.sequenceTracker.getSequenceId(portNumber, ptp.PTP_MESG_TYPE.SYNC, destinationAddress)
            msg.controlField = 0x00
            msg.logMessageInterval = pDS.logSyncInterval

            msg.originTimestamp.secondsField = 0
            msg.originTimestamp.nanosecondsField = 0

            if destinationAddress == b'':
                destinationAddress = ptp.CONST[transport]['destinationAddress']
            self.skt.sendMessage(msg.bytes(), transport, portNumber, destinationAddress)

            if self.defaultDS.twoStepFlag:
                self.initFollowUp(portNumber, destinationAddress, msg.sequenceId)

    def initFollowUp(self, portNumber, destinationAddress, sequenceId):
        # FIX: get TS7 from tofino
        ts = time.clock_gettime_ns(time.CLOCK_REALTIME)
        timeStamp = ptp.TimeStamp
        timeStamp.secondsField = ts // 1000000000
        timeStamp.nanosecondsField = ts % 1000000000

        self.sendFollowUp(portNumber, destinationAddress, sequenceId, timeStamp)

    def sendFollowUp(self, portNumber, destinationAddress, sequenceId, timeStamp):
        port = self.portList[portNumber]
        if port.portDS.portState == PTP_STATE.MASTER:
            print("[SEND] Follow Up (Port %d)" % (portNumber))
            pDS = self.portList[portNumber].portDS
            transport = self.portList[portNumber].transport
            msg = ptp.Follow_Up()

            msg.transportSpecific = ptp.CONST[transport]['transportSpecific']
            msg.messageType = ptp.PTP_MESG_TYPE.FOLLOW_UP
            msg.versionPTP = pDS.versionNumber
            msg.messageLength = ptp.Header.parser.size + ptp.Follow_Up.parser.size
            msg.domainNumber = self.defaultDS.domainNumber
            if pDS.portState == ptp.PTP_STATE.MASTER:
                msg.flagField.alternateMasterFlag = False
            else:
                print("[WARN] Alternate Master not Implemented")
            msg.flagField.unicastFlag = destinationAddress != b''
            msg.flagField.profile1 = False
            msg.flagField.profile2 = False
            msg.correctionField = 0
            msg.sourcePortIdentity = copy(pDS.portIdentity)
            msg.sequenceId = sequenceId
            msg.controlField = 0x02
            msg.logMessageInterval = pDS.logSyncInterval

            msg.preciseOriginTimestamp = timeStamp

            if destinationAddress == b'':
                destinationAddress = ptp.CONST[transport]['destinationAddress']
            self.skt.sendMessage(msg.bytes(), transport, portNumber, destinationAddress)

    ## Recv Messages ##

    def recvMessage(self, buffer, metadata):
        hdr = ptp.Header(buffer)
        portNumber = metadata['portNumber']

        if hdr.domainNumber != self.defaultDS.domainNumber:
            print("[WARN] Ignoring inter domain PTP message")
        elif hdr.sourcePortIdentity.clockIdentity == self.defaultDS.clockIdentity:
            if hdr.sourcePortIdentity == self.portList[portNumber].portDS.sourcePortIdentity:
                print("[WARN] Message received by sending port (%d)" % (portNumber))
            else:
                print("[WARN] Message received by sending clock (%d)" % (portNumber))
                # FIX: put all but lowest numbered port in PASSIVE state
        else:
            # FIX: Handle all message types
            if hdr.messageType == ptp.PTP_MESG_TYPE.ANNOUNCE:
                self.recvAnnounce(ptp.Announce(buffer), portNumber)
            elif hdr.messageType == ptp.PTP_MESG_TYPE.SYNC:
                self.recvSync(ptp.Sync(buffer), portNumber)
            elif hdr.messageType == ptp.PTP_MESG_TYPE.FOLLOW_UP:
                self.recvFollowUp(ptp.Follow_Up(buffer), portNumber)
            else:
                print("[WARN] (%d) Message Type Not Implemented: %d" % (portNumber, hdr.messageType))

    def recvAnnounce(self, msg, portNumber):
        print("[RECV] (%d) Announce" % (portNumber))
        pDS = self.portList[portNumber].portDS
        if pDS.portState in (ptp.PTP_STATE.INITIALIZING, ptp.PTP_STATE.DISABLED, ptp.PTP_STATE.FAULTY):
            print("[RECV] (%d) Ignoring Announce due to state" % (portNumber))
        elif pDS.portState == ptp.PTP_STATE.SLAVE and self.parentDS.parentPortIdentity == msg.sourcePortIdentity:
            print("[RECV] (%d) Received Announce from Master" % (portNumber))
            self.updateS1(msg)
        else:
            print("[RECV] (%d) Updating ForeignMasterList" % (portNumber))
            self.portList[portNumber].updateForeignMasterList(msg)

    def recvSync(self, msg, portNumber):
        print("[RECV] (%d) Sync" % (portNumber))
        pDS = self.portList[portNumber].portDS
        if pDS.portState in (PTP_STATE.INITIALIZING, PTP_STATE.DISABLED, PTP_STATE.FAULTY):
            print("[RECV] (%d) Ignoring Sync due to state" % (portNumber))
        elif pDS.portState not in (PTP_STATE.SLAVE, PTP_STATE.UNCALIBRATED):
            print("[RECV] (%d) Ignoring Sync due to state" % (portNumber))
        elif msg.sourcePortIdentity != self.parentDS.parentPortIdentity:
            print("[RECV] (%d) Ignoring Sync from unknown master" % (portNumber))
        else:
            # FIX: get syncEventIngressTimestamp
            if msg.flagField.twoStepFlag:
                pass # wait for follow up
            else:
                pass # synchronize

    def recvFollowUp(self, msg, portNumber):
        print("[RECV] (%d) Follow Up" % (portNumber))
        pDS = self.portList[portNumber].portDS
        if pDS.portState in (PTP_STATE.INITIALIZING, PTP_STATE.DISABLED, PTP_STATE.FAULTY):
            print("[RECV] (%d) Ignoring Follow Up due to state" % (portNumber))
        elif pDS.portState not in (PTP_STATE.SLAVE, PTP_STATE.UNCALIBRATED):
            print("[RECV] (%d) Ignoring Follow Up due to state" % (portNumber))
        elif msg.sourcePortIdentity != self.parentDS.parentPortIdentity:
            print("[RECV] (%d) Ignoring Follow Up from unknown master" % (portNumber))
        else:
            pass # Look up Sync & Synchronize

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

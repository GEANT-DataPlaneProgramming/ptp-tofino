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
import random
import time
import asyncio
import ptp
from ptp_transport import Socket
from ptp_datasets import DefaultDS, CurrentDS, ParentDS, TimePropertiesDS, PortDS, ForeignMasterDS
from ptp_datasets import TransparentClockDefaultDS, TransparentClockPortDS, BMC_Entry
from ptp import PTP_STATE, PTP_DELAY_MECH

# TODO: Fix Logging

## Custom Classes ##

class Synchronize:
    def __init__(self):
        self.delayMechanism = None
        self.sourcePortIdentity = None #(?)

        self.sync = None
        self.follow_up = None # if two step
        self.syncEventIngressTimestamp = None

        # E2E
        self.delayReqEgressTimestamp = None # When Delay_Req was sent
        self.delay_req = None
        self.delay_resp = None

        # P2P
        self.pdelayReqEgressTimestamp = None # When Pdelay_Req was sent
        self.pdelayRespIngressTimestamp = None # When Pdelay_Resp was received
        self.pdelay_resp = None # From Pdelay_Resp
        self.pdelay_resp_follow_up = None # From Pdelay_Resp

        self.meanPathDelay = None
        self.offsetFromMaster = None

    def isReady(self):
        ready = False
        if not self.sync or not self.syncEventIngressTimestamp:
            print("Need Sync")
        elif self.sync.flagField.twoStepFlag and not self.follow_up:
            print("Need Follow Up")
        elif self.delayMechanism == PTP_DELAY_MECH.E2E:
            if not self.delayReqEgressTimestamp or not self.delay_resp:
                print("Need Delay Request/Response")
            else:
                ready = True
        elif not self.pdelay_resp or not self.pdelay_resp_follow_up:
            print("Need Pdelay Response/Follow Up")
        elif not self.pdelayReqEgressTimestamp or not self.pdelayRespIngressTimestamp:
            print("Need P2P Timestamps")
        else:
            ready = True
        return ready

    def calcOffsetFromMaster(self):
        if not self.isReady(): return # Debug
        syncEventIngressTimestamp = self.syncEventIngressTimestamp
        meanPathDelay = self.meanPathDelay

        if self.sync.flagField.twoStepFlag:
            preciseOriginTimestamp = self.follow_up.preciseOriginTimestamp.ns()
            offsetFromMaster = syncEventIngressTimestamp - preciseOriginTimestamp - meanPathDelay
            offsetFromMaster -= self.sync.correctionField / 2**16
            offsetFromMaster -= self.follow_up.correctionField / 2**16
        else:
            originTimestamp = self.sync.originTimestamp.ns()
            offsetFromMaster = syncEventIngressTimestamp - originTimestamp - meanPathDelay
            offsetFromMaster -= self.sync.correctionField / 2**16

        self.offsetFromMaster = offsetFromMaster
        print("[INFO] Offset From Master: %d" % (offsetFromMaster))


    def calcMeanPathDelay(self):
        if not self.isReady(): return # Debug
        if self.delayMechanism == PTP_DELAY_MECH.E2E:
            t2 = self.syncEventIngressTimestamp
            t3 = self.delayReqEgressTimestamp
            receiveTimestamp = self.delay_resp.receiveTimestamp.ns()

            if self.sync.flagField.twoStepFlag:
                preciseOriginTimestamp = self.follow_up.preciseOriginTimestamp.ns()
                meanPathDelay = (t2 - t3) + (receiveTimestamp - preciseOriginTimestamp)
                meanPathDelay -= self.sync.correctionField / 2**16
                meanPathDelay -= self.follow_up.correctionField / 2**16
                meanPathDelay -= self.delay_resp.correctionField / 2**16
                meanPathDelay /= 2
            else:
                originTimestamp = self.sync.originTimestamp.ns()
                meanPathDelay = (t2 - t3) + (receiveTimestamp - originTimestamp)
                meanPathDelay -= self.sync.correctionField / 2**16
                meanPathDelay -= self.delay_resp.correctionField / 2**16
                meanPathDelay /= 2

        else:
            t1 = self.pdelayReqEgressTimestamp
            t4 = self.pdelayRespIngressTimestamp

            if self.pdelay_resp.flagField.twoStepFlag:
                responseOriginTimestamp = self.pdelay_resp_follow_up.responseOriginTimestamp.ns()
                requestReceiptTimestamp = self.pdelay_resp.requestReceiptTimestamp.ns()
                meanPathDelay = (t4 - t1) - (responseOriginTimestamp - requestReceiptTimestamp)
                meanPathDelay -= self.pdelay_resp.correctionField / 2**16
                meanPathDelay -= self.pdelay_resp_follow_up.correctionField / 2**16
                meanPathDelay /= 2
            else:
                pdelay_resp_correctionField = self.pdelay_resp.correctionField / 2**16
                meanPathDelay = ((t4 - t1) - pdelay_resp_correctionField) / 2

        self.meanPathDelay = meanPathDelay
        print("[INFO] Mean Path Delay: %d" % (meanPathDelay))

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
    def __init__(self, owner):
        self.task = None
        self.owner = owner

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.job())

    def _loop(self):
        self.task = asyncio.create_task(self.job())

    def restart(self):
        self.stop()
        self.start()

    def stop(self):
        if self.task:
            self.task.cancel()

    def job(self):
        pass

class Announce_Timer(Timer):
    async def job(self):
        self.owner.clock.send_Announce(self.owner)
        interval = 2 ** self.owner.portDS.logAnnounceInterval
        await asyncio.sleep(interval)
        self._loop()

class Sync_Timer(Timer):
    async def job(self):
        self.owner.clock.send_Sync(self.owner)
        interval = 2 ** self.owner.portDS.logSyncInterval
        await asyncio.sleep(interval)
        self._loop()

class State_Decision_Event_Timer(Timer):
    async def job(self):
        await asyncio.sleep(self.owner.announceInterval)
        self.owner.stateDecisionEvent()
        self._loop()

class Qualification_Timeout_Expires_Timer(Timer):
    async def job(self):
        n = self.owner.clock.currentDS.stepsRemoved + 1 if self.owner.state_decision_code == "M3" else 0
        announceInterval = 2 ** self.owner.portDS.logAnnounceInterval
        n = self.owner.clock.currentDS.stepsRemoved + 1
        qualificationTimeoutInterval = n * announceInterval
        await asyncio.sleep(qualificationTimeoutInterval)
        self.owner.qualificationTimeoutEvent()

class Announce_Receipt_Timeout_Expires_Timer(Timer):
    async def job(self):
        announceInterval = 2 ** self.owner.portDS.logAnnounceInterval
        announceReceiptTimeoutInterval = self.owner.portDS.announceReceiptTimeout * announceInterval
        announceReceiptTimeoutInterval += (announceInterval * random.random())
        await asyncio.sleep(announceReceiptTimeoutInterval)
        self.owner.announceReceiptTimeoutEvent()

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
        self.qualificationTimeoutTimer = Qualification_Timeout_Expires_Timer(self)
        self.announeTimer = Announce_Timer(self)
        self.syncTimer = Sync_Timer(self)
        self.announceReceiptTimeoutTimer = Announce_Receipt_Timeout_Expires_Timer(self)

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
            self.announeTimer.start()
            self.syncTimer.start()

        # 9.2.6.10
        if self.next_state == PTP_STATE.PRE_MASTER:
            self.qualificationTimeoutTimer.start()

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
        self.synchronize = Synchronize()
        # The logAnnounceInterval could be different per-port, but the standard treats it as being
        # the same throughout a domain. The default value is stored here for convience.
        self.announceInterval = 2 ** profile['portDS.logAnnounceInterval']
        self.state_decision_event_timer = State_Decision_Event_Timer(self)
        self.state_decision_event_timer.start()
        for i in range(numberPorts):
            self.portList[i+1] = Port(profile, self, i + 1)
        self.sequenceTracker = SequenceTracker() # FIX: per port(?)
        self.skt = Socket(interface, self.recv_message)
        self.listeningTransition()
        # self.skt.listen() # FIX: should this be before transition

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

    def send_Announce(self, port):

        # TODO: ensure port is in proper state
        pDS = port.portDS
        portNumber = pDS.portIdentity.portNumber
        transport = port.transport
        print("[SEND] ANNOUNCE (Port %d)" % (portNumber))
        msg = ptp.Announce()

        # Header fields
        msg.transportSpecific = 0
        msg.messageType = ptp.PTP_MESG_TYPE.ANNOUNCE
        msg.versionPTP = pDS.versionNumber
        msg.messageLength = ptp.Header.parser.size + ptp.Announce.parser.size
        msg.domainNumber = self.defaultDS.domainNumber
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
        msg.sequenceId = self.sequenceTracker.getSequenceId(portNumber, ptp.PTP_MESG_TYPE.ANNOUNCE, b'')
        msg.controlField = 0x05
        msg.logMessageInterval = pDS.logAnnounceInterval

        # Announce fields
        msg.originTimestamp.secondsField = 0 # UInt48
        msg.originTimestamp.nanosecondsField = 0 # UInt32
        msg.currentUtcOffset = self.timePropertiesDS.currentUtcOffset # Int16
        msg.grandmasterPriority1 = self.parentDS.grandmasterPriority1 # UInt8
        msg.grandmasterClockQuality = copy(self.parentDS.grandmasterClockQuality)
        msg.grandmasterPriority2 = self.parentDS.grandmasterPriority1 # UInt8
        msg.grandmasterIdentity = self.parentDS.grandmasterIdentity # Octet[8]
        msg.stepsRemoved = self.currentDS.stepsRemoved # UInt16
        msg.timeSource = self.timePropertiesDS.timeSource # Enum8

        self.skt.send_message(msg.bytes(), transport, portNumber)

    def send_Sync(self, port):
        pDS = port.portDS
        portNumber = pDS.portIdentity.portNumber
        transport = port.transport
        if pDS.portState == PTP_STATE.MASTER:
            print("[SEND] SYNC (Port %d)" % (portNumber))
            msg = ptp.Sync()
            msg.transportSpecific = 0
            msg.messageType = ptp.PTP_MESG_TYPE.SYNC
            msg.versionPTP = pDS.versionNumber
            msg.messageLength = ptp.Header.parser.size + ptp.Sync.parser.size
            msg.domainNumber = self.defaultDS.domainNumber
            if pDS.portState == ptp.PTP_STATE.MASTER:
                msg.flagField.alternateMasterFlag = False
            else:
                print("[WARN] Alternate Master not Implemented")
            msg.flagField.twoStepFlag = self.defaultDS.twoStepFlag
            msg.flagField.profile1 = False
            msg.flagField.profile2 = False
            msg.correctionField = 0
            msg.sourcePortIdentity = copy(pDS.portIdentity)
            msg.sequenceId = self.sequenceTracker.getSequenceId(portNumber, ptp.PTP_MESG_TYPE.SYNC, b'')
            msg.controlField = 0x00
            msg.logMessageInterval = pDS.logSyncInterval

            msg.originTimestamp.secondsField = 0
            msg.originTimestamp.nanosecondsField = 0

            egressTimestamp = self.skt.send_message(msg.bytes(), transport, portNumber, True)

            if self.defaultDS.twoStepFlag:
                self.send_Follow_Up(portNumber, msg.sequenceId, egressTimestamp)

    def send_Follow_Up(self, portNumber, sequenceId, egressTimestamp):
        port = self.portList[portNumber]
        if port.portDS.portState == PTP_STATE.MASTER:
            print("[SEND] Follow Up (Port %d)" % (portNumber))
            pDS = self.portList[portNumber].portDS
            transport = self.portList[portNumber].transport
            msg = ptp.Follow_Up()

            # Header fields
            msg.transportSpecific = 0
            msg.messageType = ptp.PTP_MESG_TYPE.FOLLOW_UP
            msg.versionPTP = pDS.versionNumber
            msg.messageLength = ptp.Header.parser.size + ptp.Follow_Up.parser.size
            msg.domainNumber = self.defaultDS.domainNumber
            msg.flagField.profile1 = False
            msg.flagField.profile2 = False
            msg.correctionField = 0
            msg.sourcePortIdentity = copy(pDS.portIdentity)
            msg.sequenceId = sequenceId
            msg.controlField = 0x02
            msg.logMessageInterval = pDS.logSyncInterval

            # Follow_Up fields
            msg.preciseOriginTimestamp = ptp.TimeStamp(egressTimestamp)

            self.skt.send_message(msg.bytes(), transport, portNumber)

    def send_Delay_Req(self, portNumber):
        """9.5.11, 11.3"""
        pDS = self.portList[portNumber].portDS
        if pDS.portState in (PTP_STATE.SLAVE, PTP_STATE.UNCALIBRATED):
            if pDS.delayMechanism == PTP_DELAY_MECH.E2E:
                print("[SEND] (%d) Delay_Req " % (portNumber))
                transport = self.portList[portNumber].transport
                msg = ptp.Delay_Req()

                # Header fields
                msg.transportSpecific = 0
                msg.messageType = ptp.PTP_MESG_TYPE.DELAY_REQ
                msg.versionPTP = pDS.versionNumber
                msg.messageLength = ptp.Header.parser.size + msg.parser.size
                msg.domainNumber = self.defaultDS.domainNumber
                msg.flagField.profile1 = False
                msg.flagField.profile2 = False
                msg.correctionField = 0
                msg.sourcePortIdentity = copy(pDS.portIdentity)
                msg.sequenceId = self.sequenceTracker.getSequenceId(portNumber, msg.messageType, b'')
                msg.controlField = 0x01 # 13.3.2.10, Table 23
                msg.logMessageInterval = 0x7F # 13.3.2.11, Table 24
                msg.originTimestamp = ptp.TimeStamp(0)

                # Felay_Req fields
                self.synchronize.delay_req = msg
                self.synchronize.delay_resp = None

                egressTimestamp = self.skt.send_message(msg.bytes(), transport, portNumber, True)
                self.synchronize.delayReqEgressTimestamp = egressTimestamp

    def send_Delay_Resp(self, portNumber, delay_req, delayReqEventIngressTimestamp):
        """9.5.12, 11.3"""
        pDS = self.portList[portNumber].portDS
        if pDS.portState == PTP_STATE.MASTER and pDS.delayMechanism == PTP_DELAY_MECH.E2E:
            print("[SEND] (%d) Delay_Resp " % (portNumber))
            transport = self.portList[portNumber].transport
            msg = ptp.Delay_Resp()
            # Header fields
            msg.transportSpecific = 0
            msg.messageType = ptp.PTP_MESG_TYPE.DELAY_RESP
            msg.versionPTP = pDS.versionNumber
            msg.messageLength = ptp.Header.parser.size + msg.parser.size
            msg.domainNumber = delay_req.domainNumber
            msg.flagField.profile1 = False
            msg.flagField.profile2 = False
            msg.correctionField = delay_req.correctionField
            msg.sourcePortIdentity = copy(pDS.portIdentity)
            msg.sequenceId = delay_req.sequenceId # 11.3.2
            msg.controlField = 0x03 # 13.3.2.10, Table 23
            msg.logMessageInterval = pDS.logMinDelayReqInterval # 13.3.2.11, Table 24
            # Delay_Resp fields
            msg.receiveTimestamp = ptp.TimeStamp(delayReqEventIngressTimestamp)
            msg.requestingPortIdentity = delay_req.sourcePortIdentity

            self.skt.send_message(msg.bytes(), transport, portNumber)

    ## Recv Messages ##

    def recv_message(self, buffer, portNumber, timestamp):
        hdr = ptp.Header(buffer)

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
                self.recv_Announce(ptp.Announce(buffer), portNumber)
            elif hdr.messageType == ptp.PTP_MESG_TYPE.SYNC:
                self.recv_Sync(ptp.Sync(buffer), portNumber, timestamp)
            elif hdr.messageType == ptp.PTP_MESG_TYPE.FOLLOW_UP:
                self.recv_Follow_Up(ptp.Follow_Up(buffer), portNumber)
            elif hdr.messageType == ptp.PTP_MESG_TYPE.DELAY_REQ:
                self.recv_Delay_Req(ptp.Delay_Req(buffer), portNumber, timestamp)
            elif hdr.messageType == ptp.PTP_MESG_TYPE.DELAY_RESP:
                self.recv_Delay_Resp(ptp.Delay_Resp(buffer), portNumber)
            else:
                print("[WARN] (%d) Message Type Not Implemented: %d" % (portNumber, hdr.messageType))

    def recv_Announce(self, msg, portNumber):
        print("[RECV] (%d) Announce" % (portNumber))
        pDS = self.portList[portNumber].portDS
        self.portList[portNumber].announceReceiptTimeoutTimer.restart()
        if pDS.portState in (ptp.PTP_STATE.INITIALIZING, ptp.PTP_STATE.DISABLED, ptp.PTP_STATE.FAULTY):
            print("[RECV] (%d) Ignoring Announce due to state" % (portNumber))
        elif pDS.portState == ptp.PTP_STATE.SLAVE and self.parentDS.parentPortIdentity == msg.sourcePortIdentity:
            print("[RECV] (%d) Received Announce from Master" % (portNumber))
            self.updateS1(msg)
        else:
            print("[RECV] (%d) Updating ForeignMasterList" % (portNumber))
            self.portList[portNumber].updateForeignMasterList(msg)

    def recv_Sync(self, msg, portNumber, ingressTimestamp):
        print("[RECV] (%d) Sync" % (portNumber))
        pDS = self.portList[portNumber].portDS
        if pDS.portState in (PTP_STATE.INITIALIZING, PTP_STATE.DISABLED, PTP_STATE.FAULTY):
            print("[RECV] (%d) Ignoring Sync due to state" % (portNumber))
        elif pDS.portState not in (PTP_STATE.SLAVE, PTP_STATE.UNCALIBRATED):
            print("[RECV] (%d) Ignoring Sync due to state" % (portNumber))
        elif msg.sourcePortIdentity != self.parentDS.parentPortIdentity:
            print("[RECV] (%d) Ignoring Sync from unknown master" % (portNumber))
        else:
            self.synchronize.delayMechanism = pDS.delayMechanism
            self.synchronize.sync = msg
            self.synchronize.syncEventIngressTimestamp = ingressTimestamp
            self.synchronize.follow_up = None
            # FIX: get syncEventIngressTimestamp
            if not msg.flagField.twoStepFlag:
                self.synchronize.calcOffsetFromMaster()

    def recv_Follow_Up(self, msg, portNumber):
        print("[RECV] (%d) Follow Up" % (portNumber))
        pDS = self.portList[portNumber].portDS
        if pDS.portState in (PTP_STATE.INITIALIZING, PTP_STATE.DISABLED, PTP_STATE.FAULTY):
            print("[RECV] (%d) Ignoring Follow Up due to state" % (portNumber))
        elif pDS.portState not in (PTP_STATE.SLAVE, PTP_STATE.UNCALIBRATED):
            print("[RECV] (%d) Ignoring Follow Up due to state" % (portNumber))
        elif msg.sourcePortIdentity != self.synchronize.sync.sourcePortIdentity \
            or msg.sequenceId != self.synchronize.sync.sequenceId:
            print("[RECV] (%d) Ignoring Unexpected Follow_Up" % (portNumber))
        elif msg.sourcePortIdentity != self.parentDS.parentPortIdentity:
            print("[RECV] (%d) Ignoring Follow_Up from unknown master" % (portNumber))
        else:
            self.synchronize.follow_up = msg
            if not self.synchronize.isReady(): self.send_Delay_Req(portNumber) # DEBUG
            self.synchronize.calcOffsetFromMaster()

    def recv_Delay_Req(self, msg, portNumber, ingressTimestamp):
        print("[RECV] (%d) Delay_Req" % (portNumber))
        pDS = self.portList[portNumber].portDS
        if pDS.portState != PTP_STATE.MASTER:
            print("[RECV] (%d) Ignoring Delay_Req due to state" % (portNumber))
        else:
            # TODO: send Delay_Resp
            self.send_Delay_Resp(portNumber, msg, ingressTimestamp)

    def recv_Delay_Resp(self, msg, portNumber):
        print("[RECV] (%d) Delay_Resp" % (portNumber))
        pDS = self.portList[portNumber].portDS
        if pDS.portState not in (PTP_STATE.SLAVE, PTP_STATE.UNCALIBRATED):
            print("[RECV] (%d) Ignoring Delay_Resp due to state" % (portNumber))
        elif msg.requestingPortIdentity != self.synchronize.delay_req.sourcePortIdentity \
            or msg.sequenceId != self.synchronize.delay_req.sequenceId:
            print("[RECV] (%d) Ignoring Unexpected Delay_Resp" % (portNumber))
        elif msg.sourcePortIdentity != self.parentDS.parentPortIdentity:
            print("[RECV] (%d) Ignoring Delay_Resp from non-Master" % (portNumber))
        else:
            self.synchronize.delay_resp = msg
            self.synchronize.calcMeanPathDelay()
            pDS.logMinDelayReqInterval = msg.logMessageInterval

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

async def main():
    randomClockIdentity = random.randrange(2**64).to_bytes(8, 'big') # FIX: get from interface
    parser = OptionParser()
    # FIX: Add option for providing clockIdentity (as MAC and/or IPv6?)
    # parser.add_option("-d", "--identity", action="callback", type="string", callback=formatIdentity, default=randomClockIdentity)
    parser.add_option("-n", "--ports", type="int", dest="numberPorts", default=1)
    parser.add_option("-i", "--interface", dest="interface", default='veth1')
    (options, _) = parser.parse_args()

    c = OrdinaryClock(ptp.PTP_PROFILE_E2E, randomClockIdentity, options.numberPorts, options.interface)
    await c.skt.listen()

asyncio.run(main())

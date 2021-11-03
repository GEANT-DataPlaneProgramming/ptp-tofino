#!/bin/python3

# pylint: disable=invalid-name

from copy import copy
import collections
import time
from ptp import *

### Ordinary and Boundary Clock Data Sets
## Clock Data Sets

# TODO: Retrieve HW dependant values
# TODO: Allow configured values to override PTP profile

class DefaultDS:
    # pylint: disable=too-many-instance-attributes
    def __init__(self, PTP_PROFILE, clockIdentity, numberPorts):
        # Static Members
        self.twoStepFlag = True # FIX: HW Dependant
        self.clockIdentity = clockIdentity
        self.numberPorts = numberPorts
        # Dynamic Members
        self.clockQuality = ClockQuality() # after slaveOnly
        self.clockQuality.clockClass = 248 # FIX: or 255 if slaveOnly
        self.clockQuality.clockAccuracy = 0xFE # Unknown
        self.clockQuality.offsetScaledLogVariance = 0xffff # not computed
        # Configurable Members
        self.priority1 = PTP_PROFILE['defaultDS.priority1']
        self.priority2 = PTP_PROFILE['defaultDS.priority2']
        self.domainNumber = PTP_PROFILE['defaultDS.domainNumber']
        self.slaveOnly = PTP_PROFILE['defaultDS.slaveOnly']

class CurrentDS:
    def __init__(self):
        # All members are Dynamic
        self.stepsRemoved = 0
        self.offsetFromMaster = 0 # Implementation-specific (ns * 2^16)
        self.meanPathDelay = 0 # Implementation-specific (ns * 2^16)

class ParentDS:
    def __init__(self, defaultDS):
        # All members are Dynamic
        self.parentPortIdentity = PortIdentity()
        self.parentPortIdentity.clockIdentity = defaultDS.clockIdentity
        self.parentPortIdentity.portNumber = 0
        self.parentStats = False # Computation optional
        self.observedParentOffsetScaledLogVariance = 0xFFFF # Computation optional
        self.observedParentClockPhaseChangeRate = 0x7FFFFFFF # Computation optional
        self.grandmasterIdentity = defaultDS.clockIdentity
        self.grandmasterClockQuality = copy(defaultDS.clockQuality)
        self.grandmasterPriority1 = defaultDS.priority1
        self.grandmasterPriority2 = defaultDS.priority2

class TimePropertiesDS:
    def __init__(self):
        # All members are Dynamic
        self.currentUtcOffset = 37 # TAI - UTC, No meaning when ptpTimescale is false
        self.currentUtcOffsetValid = False
        self.leap59 = False
        self.leap61 = False
        self.timeTraceable = False
        self.frequencyTraceable = False
        self.ptpTimescale = False # initialized first, use arbitary timescale
        self.timeSource = PTP_TIME_SRC.INTERNAL_OSCILLATOR

class PortDS:
    def __init__(self, profile, clockIdentity, portNumber):
        # Static Members
        self.portIdentity = PortIdentity()
        self.portIdentity.clockIdentity = clockIdentity
        self.portIdentity.portNumber = portNumber
        # Dynamic Members
        self.portState = PTP_STATE.INITIALIZING
        self.logMinDelayReqInterval = profile['portDS.logMinDelayReqInterval']
        self.peerMeanPathDelay = 0
        # Configurable Members
        self.logAnnounceInterval = profile['portDS.logAnnounceInterval']
        self.announceReceiptTimeout = profile['portDS.announceReceiptTimeout']
        self.logSyncInterval = profile['portDS.logSyncInterval']
        self.delayMechanism = profile['portDS.delayMechanism']
        self.logMinPdelayReqInterval = profile['portDS.logMinPdelayReqInterval']
        self.versionNumber = 2
        # Implementation Specific
        self.foreignMasterDS = set()

## Transparent Clock Data Sets

class TransparentClockDefaultDS:
    def __init__(self, PTP_PROFILE, clockIdentity, numberPorts):
        # Static Memebrs
        self.clockIdentity = clockIdentity
        self.numberPorts = numberPorts
        # Configurable Members
        self.delayMechanism = PTP_PROFILE['portDS.delayMechanism']
        self.primaryDomain = 0

class TransparentClockPortDS:
    def __init__(self, PTP_PROFILE, clockIdentity, portNumber):
        # Satic Members
        self.portIdentity = PortIdentity()
        self.portIdentity.clockIdentity = clockIdentity
        self.portIdentity.portNumber = portNumber
        # Dynamic Members
        self.logMinPdelayReqInterval = PTP_PROFILE['portDS.logMinPdelayReqInterval']
        self.faultyFlag = False
        self.peerMeanPathDelay = 0

## BMC Data Set
class ForeignMasterList:
    class ForeignMasterDS:
        def __init__(self, msg, portDS):
            self.foreignMasterPortIdentity = copy(msg.sourcePortIdentity)
            self.foreignMasterAnnounceMessages = 0
            self.timestamps = collections.deque([], 2)
            self.entry = BMC_Entry()
            self.update(msg, portDS)

        def update(self, msg, portDS):
            self.foreignMasterAnnounceMessages += 1
            self.entry.parse_Announce(msg, portDS)
            self.timestamps.append(time.monotonic())

    def __init__(self):
        self.entries = set()
        self.e_rbest = None

    def update(self, msg, portDS):
        for entry in self.entries:
            if entry.foreignMasterPortIdentity == msg.sourcePortIdentity:
                entry.update(msg, portDS)
                break
        else:
            self.entries.add(self.ForeignMasterDS(msg, portDS))

    # def getBest(self, announceInterval):
    #     ts_threshold = time.monotonic() - (4 * announceInterval)
    #     for entry in self.entries:
    #         if len(entry) < 2: continue
    #         if entry.timestamps[0] < ts_threshold: continue
    #         if entry.msg.stepsRemoved > 255: continue

class BMC_Entry:
    def __init__(self):
        self.gm_identity = None
        self.gm_priority_1 = None
        self.gm_priority_2 = None
        self.gm_class = None
        self.gm_accuracy = None
        self.gm_variance = None
        self.steps_removed = None
        self.sender_id = None
        self.receiver_id = None
        self.receiver_port = None

    def parse_DefaultDS(self, defaultDS):
        self.gm_identity = defaultDS.clockIdentity
        self.gm_priority_1 = defaultDS.grandmasterPriority1
        self.gm_priority_2 = defaultDS.grandmasterPriority2
        self.gm_class = defaultDS.clockQuality.clockClass
        self.gm_accuracy = defaultDS.clockQuality.clockAccuracy
        self.gm_variance = defaultDS.clockQuality.offsetScaledLogVariance
        self.steps_removed = 0
        self.sender_id = PortIdentity(defaultDS.clockIdentity)
        self.receiver_id = PortIdentity(defaultDS.clockIdentity)
        self.receiver_port = 0

    def parse_Announce(self, msg, portDS):
        self.gm_identity = msg.grandmasterIdentity
        self.gm_priority_1 = msg.grandmasterPriority1
        self.gm_priority_2 = msg.grandmasterPriority2
        self.gm_class = msg.grandmasterClockQuality.clockClass
        self.gm_accuracy = msg.grandmasterClockQuality.clockAccuracy
        self.gm_variance = msg.grandmasterClockQuality.offsetScaledLogVariance
        self.steps_removed = msg.stepsRemoved
        self.sender_id = copy(msg.sourcePortIdentity)
        self.receiver_id = copy(portDS.portIdentity)
        self.receiver_port = portDS.portIdentity.portNumber

    def part1_data(self):
        return [
            self.gm_priority_1,
            self.gm_class,
            self.gm_accuracy,
            self.gm_variance,
            self.gm_priority_2,
            self.gm_identity
        ]

    def compare(a, b):
        B_BETTER_THAN_A = 2
        B_BETTER_BY_TOPO_THAN_A = 1
        A_BETTER_THAN_B = -2
        A_BETTER_BY_TOPO_THAN_B = -1
        ERROR_1 = 0
        ERROR_2 = 0

        if a.gm_identity != b.gm_identity:
            if a.part1_data() > b.part1_data():
                return B_BETTER_THAN_A
            else:
                return A_BETTER_THAN_B
        else:
            if a.steps_removed > b.steps_removed + 1: return B_BETTER_THAN_A
            if a.steps_removed + 1 < b.steps_removed: return A_BETTER_THAN_B
            if a.steps_removed > b.steps_removed:
                if a.receiver_id < a.sender_id: return B_BETTER_THAN_A
                if a.receiver_id > a.sender_id: return B_BETTER_BY_TOPO_THAN_A
                return ERROR_1
            if a.steps_removed < b.steps_removed:
                if b.receiver_id < b.sender_id: return A_BETTER_THAN_B
                if b.receiver_id > b.sender_id: return A_BETTER_BY_TOPO_THAN_B
                return ERROR_1
            if a.sender_id > b.sender_id: return B_BETTER_BY_TOPO_THAN_A
            if a.sender_id < b.sender_id: return A_BETTER_BY_TOPO_THAN_B
            if a.receiver_port > b.receiver_port: return B_BETTER_BY_TOPO_THAN_A
            if a.receiver_port < b.receiver_port: return A_BETTER_BY_TOPO_THAN_B
            return ERROR_2

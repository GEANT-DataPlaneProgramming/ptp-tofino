#!/bin/python3

from ptp import *
from copy import copy
import collections, time

### Ordinary and Boundary Clock Data Sets
## Clock Data Sets

# TODO: Retrieve HW dependant values
# TODO: Allow configured values to override PTP profile

class DefaultDS:
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
        def __init__(self, msg):
            self.foreignMasterPortIdentity = copy(msg.sourcePortIdentity)
            self.foreignMasterAnnounceMessages = 0
            self.timestamps = collections.deque([],2)
            self.msg = None
            self.update(msg)

        def update(self, msg):
            self.foreignMasterAnnounceMessages += 1
            self.msg = msg
            self.timestamps.append(time.monotonic())

        def comparison1(self):
            return [self.msg.grandmasterPriority1,
                self.msg.grandmasterClockQuality.clockClass,
                self.msg.grandmasterClockQuality.clockAccuracy,
                self.msg.grandmasterClockQuality.offsetScaledLogVariance,
                self.msg.grandmasterPriority2,
                self.msg.grandmasterIdentity]

        def comparison2(self):
            pass

    def __init__(self):
        self.entries = set()
        self.e_rbest = None

    def update(self, msg):
        for e in self.entries:
            if e.foreignMasterPortIdentity == msg.sourcePortIdentity:
                e.update(msg)
                break
        else:
            self.entries.add(self.ForeignMasterDS(msg))

    def getBest(self, announceInterval):
        ts_threshold = time.monotonic() - (4 * announceInterval)
        for e in self.entries:
            if len(d) < 2: continue
            if e.timestamps[0] < ts_threshold: continue
            if e.msg.stepsRemoved > 255: continue

    def getBetter(self, a, b):
        if a == b:
            self.getBetterByTopo(a, b)
        else:
            pass

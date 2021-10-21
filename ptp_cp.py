#!/bin/python3

# TODO: What time scale should be used?

from enum import IntEnum
#from threading import Timer

class PTP_TIME_SRC(IntEnum):
    ATOMIC_CLOCK = 0x10
    GPS = 0x20
    TERRESTRIAL_RADIO = 0x30
    PTP = 0x40
    NTP = 0x50
    HAND_SET = 0x60
    OTHER = 0x90
    INTERNAL_OSCILLATOR = 0xA0

class PTP_PROTO(IntEnum):
    UDP_IPV4 = 1
    UDP_IPV6 = 2
    ETHERNET = 3

class PTP_STATE(IntEnum):
    INITIALIZING = 1
    FAULTY = 2
    DISABLED = 3
    LISTENING = 4
    PRE_MASTER = 5
    MASTER = 6
    PASSIVE = 7
    UNCALIBRATED = 8
    SLAVE = 9

class PTP_DELAY_MECH(IntEnum):
    E2E = 1
    P2P = 2
    DISABLED = 3

class PTP_MESG_TYPE(IntEnum):
    SYNC = 0
    DELAY_REQ = 1
    PDELAY_REQ = 2
    PDELAY_RESP = 3
    FOLLOW_UP = 8
    DELAY_RESP = 9
    PDELAY_RESP_FOLLOW_UP = 0xA
    ANNOUNCE = 0xB
    SIGNALING = 0xC
    MANAGEMENT = 0xD

### PTP Default Profiles

PTP_PROFILE_E2E = {
    'defaultDS.domainNumber' : 0,
    'portDS.logAnnounceInterval' : 1, # Range: 0 to 4
    'portDS.logSyncInterval' : 0, # Range: -1 to +1
    'portDS.logMinDelayReqInterval' : 0, # Range: 0 to 5
    'portDS.logMinPdelayReqInterval' : None, # Not set in this profile
    'portDS.announceReceiptTimeout' : 3, # Range 2 to 10
    'defaultDS.priority1' : 128,
    'defaultDS.priority2' : 128,
    'defaultDS.slaveOnly' : False, # If configurable
    'transparentClockdefaultDS.primaryDomain' : 0,
    'tau' : 1, # seconds
    'portDS.delayMechanism' : PTP_DELAY_MECH.E2E
}

PTP_PROFILE_P2P = {
    'defaultDS.domainNumber' : 0,
    'portDS.logAnnounceInterval' : 1, # Range: 0 to 4
    'portDS.logSyncInterval' : 0, # Range: -1 to +1
    'portDS.logMinDelayReqInterval' : None, # Not set in this profile
    'portDS.logMinPdelayReqInterval' : 0, # Range: 0 to 5
    'portDS.announceReceiptTimeout' : 3, # Range 2 to 10
    'defaultDS.priority1' : 128,
    'defaultDS.priority2' : 128,
    'defaultDS.slaveOnly' : False, # If configurable
    'transparentClockdefaultDS.primaryDomain' : 0,
    'tau' : 1, # seconds
    'portDS.delayMechanism' : PTP_DELAY_MECH.P2P
}

### PTP Data Types

class TimeStamp:
    def __init__(self):
        self.secondsField = None # UInt48
        self.nanosecondsField = None # UInt32

class PortIdentity:
    def __init__(self):
        self.clockIdentity = None # Octet[8]
        self.portNumber = None # UInt16

class PortAddress:
    def __init__(self):
        self.networkProtocol = None
        self.addressLength = None
        self.addressField = None

class ClockQuality:
    def __init__(self):
        self.clockClass = None
        self.clockAccuracy = None
        self.offsetScaledLogVariance = None

class TLV:
    def __init__(self):
        self.tlvType = None
        self.lengthField = None
        self.valueField = None

class PTPText:
    def __init__(self):
        self.lengthField = None
        self.textField = None

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
        self.grandmasterClockQuality = defaultDS.clockQuality
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
    def __init__(self, PTP_PROFILE, clockIdentity, portNumber):
        # Static Members
        self.portIdentity = PortIdentity()
        self.portIdentity.clockIdentity = clockIdentity
        self.portIdentity.portNumber = portNumber
        # Dynamic Members
        self.portState = PTP_STATE.INITIALIZING
        self.logMinDelayReqInterval = PTP_PROFILE['portDS.logMinDelayReqInterval']
        self.peerMeanPathDelay = 0
        # Configurable Members
        self.logAnnounceInterval = PTP_PROFILE['portDS.logAnnounceInterval']
        self.announceReceiptTimeout = PTP_PROFILE['portDS.announceReceiptTimeout']
        self.logSyncInterval = PTP_PROFILE['portDS.logSyncInterval']
        self.delayMechanism = PTP_PROFILE['portDS.delayMechanism']
        self.logMinPdelayReqInterval = PTP_PROFILE['portDS.logMinPdelayReqInterval']
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
class ForeignMasterDS:
    def __init__(self, clockIdentity, portNumber):
        self.foreignMasterPortIdentity = PortIdentity()
        self.foreignMasterPortIdentity.clockIdentity = clockIdentity
        self.foreignMasterPortIdentity.portNumber = portNumber
        self.foreignMasterAnnounceMessages = 0

## Custom Classes ##

class OrdinaryClock:
    def __init__(self, PTP_PROFILE, macAddress, numberPorts):
        clockIdentity = macAddress # FIX: convert MAC to clockIdentity
        self.defaultDS = DefaultDS(PTP_PROFILE, clockIdentity, numberPorts)
        self.currentDS = CurrentDS()
        self.parentDS = ParentDS(self.defaultDS)
        self.timePropertiesDS = TimePropertiesDS()
        self.portDS = { PortDS(PTP_PROFILE, clockIdentity, i + 1) for i in range(numberPorts) }

class TransparentClock:
    def __init__(self, PTP_PROFILE, macAddress, numberPorts):
        clockIdentity = macAddress # FIX: convert MAC to clockIdentity
        self.transparentClockDefaultDS = TransparentClockDefaultDS(PTP_PROFILE, clockIdentity, numberPorts)
        self.transparentClockPortDS = { TransparentClockPortDS(PTP_PROFILE, clockIdentity, i + 1) for i in range(numberPorts) }

c = OrdinaryClock(PTP_PROFILE_E2E, -1, 32)
tc = TransparentClock(PTP_PROFILE_E2E, -1, 32)

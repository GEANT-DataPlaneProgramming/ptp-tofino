#!/bin/python3

# TODO: What time scale should be used?

from enum import IntEnum
from threading import Timer

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

### PTP Default Profile
PTP_PROFILE = {
    'defaultDS.domainNumber' : 0,
    'portDS.logAnnounceInterval' : 1, # Range: 0 to 4
    'portDS.logSyncInterval' : 0, # Range: -1 to +1
    'portDS.logMinDelayReqInterval' : 0, # Range: 0 to 5
    'portDS.announceReceiptTimeout' : 3, # Range 2 to 10
    'defaultDS.priority1' : 128,
    'defaultDS.priority2' : 128,
    'defaultDS.slaveOnly' : False, # If configurable
    'transparentClockdefaultDS.primaryDomain' : 0,
    'tau' : 1 # seconds
}

### PTP Data Types

class TimeStamp:
    secondsField = None
    nanosecondsField = None

class PortIdentity:
    clockIdentity = None
    portNumber = None

class PortAddress:
    networkProtocol = None
    addressLength = None
    addressField = None

class ClockQuality:
    clockClass = None
    clockAccuracy = None
    offsetScaledLogVariance = None

class TLV:
    tlvType = None
    lengthField = None
    valueField = None

class PTPText:
    lengthField = None
    textField = None

### Ordinary and Boundary Clock Data Sets
## Clock Data Sets

# TODO: Retrieve HW dependant values
# TODO: Allow configured values to override PTP profile

class defaultDS:
    # Static Members
    twoStepFlag = True # HW Dependant
    clockIdentity = None # Based on MAC
    numberPorts = 32 # HW Dependant
    # Dynamic Members
    clockQuality = ClockQuality() # after slaveOnly
    clockQuality.clockClass = 248 # FIX: or 255 if slaveOnly
    clockQuality.clockAccuracy = 0xFE # Unknown
    clockQuality.offsetScaledLogVariance = 0xffff # not computed
    # Configurable Members
    priority1 = PTP_PROFILE['defaultDS.priority1']
    priority2 = PTP_PROFILE['defaultDS.priority2']
    domainNumber = PTP_PROFILE['defaultDS.domainNumber']
    slaveOnly = PTP_PROFILE['defaultDS.slaveOnly']

class currentDS:
    # All members are Dynamic
    stepsRemoved = 0
    offsetFromMaster = 0 # Implementation-specific (ns * 2^16)
    meanPathDelay = 0 # Implementation-specific (ns * 2^16)

class parentDS:
    # All members are Dynamic
    parentPortIdentity = PortIdentity()
    parentPortIdentity.clockIdentity = None # FIX: = defaultDS.clockIdentity
    parentPortIdentity.portNumber = 0
    parentStats = False # Computation optional
    observedParentOffsetScaledLogVariance = 0xFFFF # Computation optional
    observedParentClockPhaseChangeRate = 0x7FFFFFFF # Computation optional
    grandmasterIdentity = None # FIX: = defaultDS.clockIdentity
    grandmasterClockQuality = None # FIX: = defaultDS.clockQuality
    grandmasterPriority1 = None # FIX: = defaultDS.priority1
    grandmasterPriority2 = None # FIX: = defaultDS.priority2

class timePropertiesDS:
    # All members are Dynamic
    currentUtcOffset = 37 # TAI - UTC
    currentUtcOffsetValid = False
    leap59 = False
    leap61 = False
    timeTraceable = False
    frequencyTraceable = False
    ptpTimescale = False # initialized first, use arbitary timescale
    timeSource = PTP_TIME_SRC.INTERNAL_OSCILLATOR

## Port Data Sets

class PortDS:
    # Static Members
    portIdentity = None
    # Dynamic Members
    portState = None
    logMinDelayReqInterval = None
    peerMeanPathDelay = None
    # Configurable Members
    logAnnounceInterval = None
    announceReceiptTimeout = None
    logSyncInterval = None
    delayMechanism = None
    logMinPdelayReqInterval = None
    versionNumber = None

class ForeignMasterDS:
    # This should be an array or set
    foreignMasterPortIdentity = None
    foreignMasterAnnounceMessages = None

### Transparent Clock Data Sets

class transparentClockDefaultDS:
    clockIdentity = None
    numberPorts = None
    delayMechanism = None
    primaryDomain = None

class transparentClockPortDS:
    portIdentity = None
    logMinPdelayReqInterval = None
    faultyFlag = None
    peerMeanPathDelay = None

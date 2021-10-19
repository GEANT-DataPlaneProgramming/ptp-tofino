#!/bin/python3

from enum import IntEnum

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

### Ordinary and Boundary Clock Data Sets
## Clock Data Sets

class defaultDS:
    twoStepFlag = None
    clockIdentity = None
    numberPorts = None
    clockQuality = None
    priority1 = None
    priority2 = None
    domainNumber = None
    slaveOnly = None

class currentDS:
    stepsRemoved = None
    offsetFromMaster = None
    meanPathDelay = None

class parentDS:
    parentPortIdentity = None
    parentStats = None
    observedParentOffsetScaledLogVariance = None
    observedParentClockPhaseChangeRate = None
    grandmasterIdentity = None
    grandmasterClockQuality = None
    grandmasterPriority1 = None
    grandmasterPriority2 = None

class timePropertiesDS:
    currentUtcOffset = None
    currentUtcOffsetValid = None
    leap59 = None
    leap61 = None
    timeTraceable = None
    frequencyTraceable = None
    ptpTimescale = None
    timeSource = None

## Port Data Sets

class PortDS:
    portIdentity = None
    portState = None
    logMinDelayReqInterval = None
    peerMeanPathDelay = None
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

#!/bin/python3

from copy import copy

from enum import IntEnum
import struct
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

CONST = {
    PTP_PROTO.ETHERNET: {
        'transportSpecific': 0,
        'destinationAddress': struct.pack('!Q', 0x011b19000000)[2:8],
        'pDelayDestinationAdress': struct.pack('!Q', 0x0180c200000e)[2:8]
    },
    PTP_PROTO.UDP_IPV4: {},
    PTP_PROTO.UDP_IPV6: {}
}

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

    def __eq__(self, other):
        if not isinstance(other, PortIdentity): return NotImplemented
        return self.clockIdentity == other.clockIdentity and self.portNumber == other.portNumber

class PortAddress:
    def __init__(self):
        self.networkProtocol = None
        self.addressLength = None
        self.addressField = None

class ClockQuality:
    def __init__(self):
        self.clockClass = None # UInt8
        self.clockAccuracy = None # Enum8
        self.offsetScaledLogVariance = None #UInt16

class TLV:
    def __init__(self):
        self.tlvType = None
        self.lengthField = None
        self.valueField = None

class PTPText:
    def __init__(self):
        self.lengthField = None
        self.textField = None

### PTP Messages

class FlagField:
    def __init__(self):
        self.alternateMasterFlag = False
        self.twoStepFlag = False
        self.unicastFlag = False
        self.profile1 = False
        self.profile2 = False
        self.leap61 = False
        self.leap59 = False
        self.currentUtcOffsetValid = False
        self.ptpTimescale = False
        self.timeTraceable = False
        self.frequencyTraceable = False

    def parse(self, buffer):
        flagField = [[(buffer[i] >> j) & 0x01 for j in range(8)] for i in range(len(buffer))]
        self.alternateMasterFlag = flagField[0][0]
        self.twoStepFlag = flagField[0][1]
        self.unicastFlag = flagField[0][2]
        self.profile1 = flagField[0][5]
        self.profile2 = flagField[0][6]
        self.leap61 = flagField[1][0]
        self.leap59 = flagField[1][1]
        self.currentUtcOffsetValid = flagField[1][2]
        self.ptpTimescale = flagField[1][3]
        self.timeTraceable = flagField[1][4]
        self.frequencyTraceable = flagField[1][5]

    def bytes(self):
        flagField = [[False]*8,[False]*8]
        flagField[0][0] = self.alternateMasterFlag
        flagField[0][1] = self.twoStepFlag
        flagField[0][2] = self.unicastFlag
        flagField[0][5] = self.profile1
        flagField[0][6] = self.profile2
        flagField[1][0] = self.leap61
        flagField[1][1] = self.leap59
        flagField[1][2] = self.currentUtcOffsetValid
        flagField[1][3] = self.ptpTimescale
        flagField[1][4] = self.timeTraceable
        flagField[1][5] = self.frequencyTraceable
        l = [sum([(2**j) * flagField[i][j] for j in range(8) ]) for i in range(len(flagField))]
        return struct.pack('2B', *l)

class Header:
    parser = struct.Struct('!2BHBx2sq4x8sHHBb')

    def __init__(self):
        self.transportSpecific = None # Nibble
        self.messageType = None # Enumneration4
        self.versionPTP = None # UInt4
        self.messageLength = None # Uint16
        self.domainNumber = None # UInt8
        self.flagField = FlagField() # Octet[2]
        self.correctionField = None # Int64
        self.sourcePortIdentity = PortIdentity()
        # self.sourcePortIdentity.clockIdentity = None # Octet[8]
        # self.sourcePortIdentity.portNumber = None # UInt16
        self.sequenceId = None # UInt16
        self.controlField = None # UInt8
        self.logMessageInterval = None # Int8

    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.transportSpecific = t[0] >> 4
        self.messageType = t[0] & 0x0F
        self.versionPTP = t[1] & 0x0F
        self.messageLength = t[2]
        self.domainNumber = t[3]
        self.flagField.parse(t[4])
        self.correctionField = t[5]
        self.sourcePortIdentity.clockIdentity = t[6]
        self.sourcePortIdentity.portNumber = t[7]
        self.sequenceId = t[8]
        self.controlField = t[9]
        self.logMessageInterval = t[10]

    def bytes(self):
        t = (
        (self.transportSpecific << 4) | self.messageType, \
        self.versionPTP, \
        self.messageLength, \
        self.domainNumber,
        self.flagField.bytes(), \
        self.correctionField, \
        self.sourcePortIdentity.clockIdentity, \
        self.sourcePortIdentity.portNumber, \
        self.sequenceId, \
        self.controlField, \
        self.logMessageInterval \
        )
        return self.parser.pack(*t)

class Announce:
    parser = struct.Struct('!6sLhx3BHB8sHB')

    def __init__(self, buffer = None):
        self.originTimestamp = TimeStamp()
        # self.originTimestamp.secondsField = None # UInt48
        # self.originTimestamp.nanosecondsField = None # UInt32
        self.currentUtcOffset = None # Int16
        self.grandmasterPriority1 = None # UInt8
        self.grandmasterClockQuality = ClockQuality()
        # self.grandmasterClockQuality.clockClass = None # UInt8
        # self.grandmasterClockQuality.clockAccuracy = None # Enum8
        # self.grandmasterClockQuality.offsetScaledLogVariance = None # UInt16
        self.grandmasterPriority2 = None # UInt8
        self.grandmasterIdentity = None # Octet[8]
        self.stepsRemoved = None # UInt16
        self.timeSource = None # Enum8
        if (buffer): self.parse(buffer)

    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.originTimestamp.secondsField = struct.unpack('!Q', b'\x00\x00' + t[0])
        self.originTimestamp.nanosecondsField = t[1]
        self.currentUtcOffset = t[2]
        self.grandmasterPriority1 = t[3]
        self.grandmasterClockQuality.clockClass = t[4]
        self.grandmasterClockQuality.clockAccuracy = t[5]
        self.grandmasterClockQuality.offsetScaledLogVariance = t[6]
        self.grandmasterPriority2 = t[7]
        self.grandmasterIdentity = t[8]
        self.stepsRemoved = t[9]
        self.timeSource = t[10]

    def bytes(self):
        t = (
        struct.pack('!Q', self.originTimestamp.secondsField)[2:8], \
        self.originTimestamp.nanosecondsField, \
        self.currentUtcOffset, \
        self.grandmasterPriority1, \
        self.grandmasterClockQuality.clockClass, \
        self.grandmasterClockQuality.clockAccuracy, \
        self.grandmasterClockQuality.offsetScaledLogVariance, \
        self.grandmasterPriority2, \
        self.grandmasterIdentity, \
        self.stepsRemoved, \
        self.timeSource \
        )
        return self.parser.pack(*t)

class Sync:
    parser = struct.Struct('!6sL')

    def __init__(self):
        self.originTimestamp = TimeStamp()
        # self.originTimestamp.secondsField = None # UInt48
        # self.originTimestamp.nanosecondsField = None # UInt32

    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.originTimestamp.secondsField = struct.unpack('!Q', b'\x00\x00' + t[0])
        self.originTimestamp.nanosecondsField = t[1]

    def bytes(self):
        t = (
        struct.pack('!Q', self.originTimestamp.secondsField)[2:8], \
        self.originTimestamp.nanosecondsField \
        )
        return self.parser.pack(*t)

Delay_Req = Sync

class Follow_Up:
    parser = struct.Struct('!6sL')

    def __init__(self):
        self.preciseOriginTimestamp = TimeStamp()
        # self.preciseOriginTimestamp.secondsField = None # UInt48
        # self.preciseOriginTimestamp.nanosecondsField = None # UInt32

    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.preciseOriginTimestamp.secondsField = struct.unpack('!Q', b'\x00\x00' + t[0])
        self.preciseOriginTimestamp.nanosecondsField = t[1]

    def bytes(self):
        t = (
        struct.pack('!Q', self.preciseOriginTimestamp.secondsField)[2:8], \
        self.preciseOriginTimestamp.nanosecondsField \
        )
        return self.parser.pack(*t)

class Delay_Resp:
    parser = struct.Struct('!6sL8sH')

    def __init__(self):
        self.receiveTimestamp = TimeStamp()
        # self.receiveTimestamp.secondsField = None # UInt48
        # self.receiveTimestamp.nanosecondsField = None # UInt32
        self.requestingPortIdentity = PortIdentity()
        # self.requestingPortIdentity.clockIdentity = None # Octet[8]
        # self.requestingPortIdentity.portNumber = None # UInt16


    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.receiveTimestamp.secondsField = struct.unpack('!Q', b'\x00\x00' + t[0])
        self.receiveTimestamp.nanosecondsField = t[1]
        self.requestingPortIdentity.clockIdentity = t[2]
        self.requestingPortIdentity.portNumber = t[3]

    def bytes(self):
        t = (
        struct.pack('!Q', self.receiveTimestamp.secondsField)[2:8], \
        self.receiveTimestamp.nanosecondsField, \
        self.requestingPortIdentity.clockIdentity, \
        self.requestingPortIdentity.portNumber \
        )
        return self.parser.pack(*t)

class Pdelay_Req:
    parser = struct.Struct('!6sL10x')

    def __init__(self):
        self.originTimestamp = TimeStamp()
        # self.originTimestamp.secondsField = None # UInt48
        # self.originTimestamp.nanosecondsField = None # UInt32

    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.originTimestamp.secondsField = struct.unpack('!Q', b'\x00\x00' + t[0])
        self.originTimestamp.nanosecondsField = t[1]

    def bytes(self):
        t = (
        struct.pack('!Q', self.originTimestamp.secondsField)[2:8], \
        self.originTimestamp.nanosecondsField \
        )
        return self.parser.pack(*t)

class Pdelay_Resp:
    parser = struct.Struct('!6sL8sH')

    def __init__(self):
        self.requestReceiptTimestamp = TimeStamp()
        # self.receiveTimestamp.secondsField = None # UInt48
        # self.receiveTimestamp.nanosecondsField = None # UInt32
        self.requestingPortIdentity = PortIdentity()
        # self.requestingPortIdentity.clockIdentity = None # Octet[8]
        # self.requestingPortIdentity.portNumber = None # UInt16


    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.requestReceiptTimestamp.secondsField = struct.unpack('!Q', b'\x00\x00' + t[0])
        self.requestReceiptTimestamp.nanosecondsField = t[1]
        self.requestingPortIdentity.clockIdentity = t[2]
        self.requestingPortIdentity.portNumber = t[3]

    def bytes(self):
        t = (
        struct.pack('!Q', self.requestReceiptTimestamp.secondsField)[2:8], \
        self.requestReceiptTimestamp.nanosecondsField, \
        self.requestingPortIdentity.clockIdentity, \
        self.requestingPortIdentity.portNumber \
        )
        return self.parser.pack(*t)

class Pdelay_Resp_Follow_Up:
    parser = struct.Struct('!6sL8sH')

    def __init__(self):
        self.responseOriginTimestamp = TimeStamp()
        # self.receiveTimestamp.secondsField = None # UInt48
        # self.receiveTimestamp.nanosecondsField = None # UInt32
        self.requestingPortIdentity = PortIdentity()
        # self.requestingPortIdentity.clockIdentity = None # Octet[8]
        # self.requestingPortIdentity.portNumber = None # UInt16


    def parse(self, buffer):
        t = self.parser.unpack(buffer)
        self.responseOriginTimestamp.secondsField = struct.unpack('!Q', b'\x00\x00' + t[0])
        self.responseOriginTimestamp.nanosecondsField = t[1]
        self.requestingPortIdentity.clockIdentity = t[2]
        self.requestingPortIdentity.portNumber = t[3]

    def bytes(self):
        t = (
        struct.pack('!Q', self.responseOriginTimestamp.secondsField)[2:8], \
        self.responseOriginTimestamp.nanosecondsField, \
        self.requestingPortIdentity.clockIdentity, \
        self.requestingPortIdentity.portNumber \
        )
        return self.parser.pack(*t)

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
    def __init__(self, portIdentity):
        self.foreignMasterPortIdentity = copy(portIdentity)
        self.foreignMasterAnnounceMessages = 0

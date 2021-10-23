#!/bin/python3

# TODO: What time scale should be used?

import ptp
#from threading import Timer

## Custom Classes ##

class OrdinaryClock:
    def __init__(self, PTP_PROFILE, macAddress, numberPorts):
        clockIdentity = macAddress # FIX: convert MAC to clockIdentity
        self.defaultDS = ptp.DefaultDS(PTP_PROFILE, clockIdentity, numberPorts)
        self.currentDS = ptp.CurrentDS()
        self.parentDS = ptp.ParentDS(self.defaultDS)
        self.timePropertiesDS = ptp.TimePropertiesDS()
        self.portDS = { ptp.PortDS(PTP_PROFILE, clockIdentity, i + 1) for i in range(numberPorts) }

class TransparentClock:
    def __init__(self, PTP_PROFILE, macAddress, numberPorts):
        clockIdentity = macAddress # FIX: convert MAC to clockIdentity
        self.transparentClockDefaultDS = ptp.TransparentClockDefaultDS(PTP_PROFILE, clockIdentity, numberPorts)
        self.transparentClockPortDS = { ptp.TransparentClockPortDS(PTP_PROFILE, clockIdentity, i + 1) for i in range(numberPorts) }

### Testing ###

# c = OrdinaryClock(ptp.PTP_PROFILE_E2E, -1, 32)
# tc = TransparentClock(ptp.PTP_PROFILE_E2E, -1, 32)

h1 = ptp.Header()
h1.transportSpecific = 0 # Nibble
h1.messageType = ptp.PTP_MESG_TYPE.ANNOUNCE # Enumneration4
h1.versionPTP = 2 # UInt4
h1.messageLength = 34 # Uint16
h1.domainNumber = 0 # UInt8
h1.flagField = b'\x00\x00' # Octet[2]
h1.correctionField = 0 # Int64
h1.sourcePortIdentity.clockIdentity = b'ABCDEFGH' # Octet[8]
h1.sourcePortIdentity.portNumber = 1 # UInt16
h1.sequenceId = 42 # UInt16
h1.controlField = 0x05 # UInt8
h1.logMessageInterval = 1 # Int8

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

c = OrdinaryClock(ptp.PTP_PROFILE_E2E, -1, 32)
tc = TransparentClock(ptp.PTP_PROFILE_E2E, -1, 32)

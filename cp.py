#!/bin/python3

# TODO: What time scale should be used?

import ptp, threading, random
#from threading import Timer

## Custom Classes ##

class Timer:
    def __init__(self, interval, function, args):
        self.i = interval
        self.f = function
        self.args = args

    def _run(self, args):
        self.start()
        self.f(args)

    def start(self):
        self.t = threading.Timer(self.i, self._run, self.args)
        self.t.start()

    def stop(self):
        self.t.cancel()

    def reset(self):
        self.stop()
        self.start()

class OrdinaryClock:
    def __init__(self, PTP_PROFILE, macAddress, numberPorts):
        print("[EVENT] POWERUP (All Ports)")
        print("[STATE] INITIALIZING (All Ports)")
        clockIdentity = macAddress # FIX: convert MAC to clockIdentity
        self.defaultDS = ptp.DefaultDS(PTP_PROFILE, clockIdentity, numberPorts)
        self.currentDS = ptp.CurrentDS()
        self.parentDS = ptp.ParentDS(self.defaultDS)
        self.timePropertiesDS = ptp.TimePropertiesDS()
        self.portDS = {}
        for i in range(numberPorts):
            self.portDS[i+1] = ptp.PortDS(PTP_PROFILE, clockIdentity, i + 1)
        # Open Network Socket
        self.listeningTransition()

    def listeningTransition(self):
        print("[STATE] LISTENING (All Ports)")
        for p in self.portDS.values():
            p.portState = ptp.PTP_STATE.LISTENING
            announceInterval = 2 ** p.logAnnounceInterval
            announceReceiptTimeoutInterval = p.announceReceiptTimeout * announceInterval
            interval = announceReceiptTimeoutInterval + (announceInterval * random.random())
            p.announceReceiptTimeoutTimer = Timer(interval, self.announceReceiptTimeoutEvent, [p.portIdentity.portNumber])
            p.announceReceiptTimeoutTimer.start()

    def masterTransition(self, portNumber):
        print("[STATE] MASTER (Port %d)" % (portNumber))
        p = self.portDS[portNumber]
        p.announceReceiptTimeoutTimer.stop()
        p.portState = ptp.PTP_STATE.MASTER
        announceInterval = 2 ** p.logAnnounceInterval
        p.announeTimer = Timer(announceInterval, self.sendAnnounce, [portNumber])
        p.announeTimer.start()
        syncInterval = 2 ** p.logSyncInterval
        p.syncTimer = Timer(syncInterval, self.sendSync, [portNumber])
        p.syncTimer.start()

    def updateM1M2(self, portNumber):
        print("[STATE] Decision code M1/M2 (Port %d)" % (portNumber))
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
        print("[STATE] Decision code M3 (Port %d)" % (portNumber))

    def updateP1P2(self, portNumber):
        print("[STATE] Decision code P1/P2 (Port %d)" % (portNumber))

    def updateS1(self, portNumber):
        pass

    def powerupEvent(self):
        pass

    def initializeEvent(self):
        pass

    def decisionEvent(self):
        pass

    def recommendedStateEvent(self):
        pass

    def announceReceiptTimeoutEvent(self, portNumber):
        print("[EVENT] ANNOUNCE_RECEIPT_TIMEOUT_EXPIRES (Port %d)" % (portNumber))
        valid_states = (ptp.PTP_STATE.LISTENING, ptp.PTP_STATE.UNCALIBRATED, ptp.PTP_STATE.SLAVE, ptp.PTP_STATE.PASSIVE)
        if self.portDS[portNumber].portState in valid_states:
            p = self.portDS[portNumber]
            if ptp.PTP_STATE.SLAVE in [p.portState for p in self.portDS.values() if p.portIdentity.portNumber != portNumber]:
                self.updateM3(portNumber)
            else:
                self.updateM1M2(portNumber)
            self.masterTransition(portNumber)
        else:
            print("[WARN] UNEXPECTED CONDITION")

    def qualificationTimeoutEvent(self, port):
        pass

    def masterSelectedEvent(self, port):
        pass

    def sendAnnounce(self, portNumber):
        print("[SEND] ANNOUNCE (Port %d)" % (portNumber))
        p = self.portDS[portNumber]
        hdr = ptp.Header()
        msg = ptp.Announce()

        hdr.transportSpecific = None # FIX: = self.hwConst.transportSpecific
        hdr.messageType = ptp.PTP_MESG_TYPE.ANNOUNCE
        hdr.versionPTP = p.versionNumber
        hdr.messageLength = ptp.Header.parser.size + ptp.Announce.parser.size
        hdr.domainNumber = self.defaultDS.domainNumber
        hdr.flagField = None # Octet[2] FIX: flags
        hdr.correctionField = 0 # MsgType dependant
        hdr.sourcePortIdentity.clockIdentity = p.portIdentity.clockIdentity
        hdr.sourcePortIdentity.portNumber = p.portIdentity.portNumber
        hdr.sequenceId = None # UInt16 FIX: track sequenceIds
        hdr.controlField = 0x05 # MsgType dependant
        hdr.logMessageInterval = p.logAnnounceInterval # MsgType dependant

        msg.originTimestamp.secondsField = 0 # UInt48
        msg.originTimestamp.nanosecondsField = 0 # UInt32
        msg.currentUtcOffset = self.timePropertiesDS.currentUtcOffset # Int16
        msg.grandmasterPriority1 = self.parentDS.grandmasterPriority1 # UInt8
        msg.grandmasterClockQuality.clockClass = self.parentDS.grandmasterClockQuality.clockClass # UInt8
        msg.grandmasterClockQuality.clockAccuracy = self.parentDS.grandmasterClockQuality.clockAccuracy # Enum8
        msg.grandmasterClockQuality.offsetScaledLogVariance = self.parentDS.grandmasterClockQuality.offsetScaledLogVariance # UInt16
        msg.grandmasterPriority2 = self.parentDS.grandmasterPriority1 # UInt8
        msg.grandmasterIdentity = self.parentDS.grandmasterIdentity # Octet[8]
        msg.stepsRemoved = self.currentDS.stepsRemoved # UInt16
        msg.timeSource = self.timePropertiesDS.timeSource # Enum8

        #self.sendMessage(hdr.bytes() + msg.bytes(), portNumber, DST_MULTICAST)

    def sendSync(self, portNumber):
        print("[SEND] SYNC (Port %d)" % (portNumber))
        msg = ptp.Sync()

class TransparentClock:
    def __init__(self, PTP_PROFILE, macAddress, numberPorts):
        clockIdentity = macAddress # FIX: convert MAC to clockIdentity
        self.transparentClockDefaultDS = ptp.TransparentClockDefaultDS(PTP_PROFILE, clockIdentity, numberPorts)
        self.transparentClockPortDS = { ptp.TransparentClockPortDS(PTP_PROFILE, clockIdentity, i + 1) for i in range(numberPorts) }

### Events ###




### Testing ###

c = OrdinaryClock(ptp.PTP_PROFILE_E2E, -1, 3)
# tc = TransparentClock(ptp.PTP_PROFILE_E2E, -1, 32)

# h1 = ptp.Header()
# h1.transportSpecific = 0 # Nibble
# h1.messageType = ptp.PTP_MESG_TYPE.ANNOUNCE # Enumneration4
# h1.versionPTP = 2 # UInt4
# h1.messageLength = 34 # Uint16
# h1.domainNumber = 0 # UInt8
# h1.flagField = b'\x00\x00' # Octet[2]
# h1.correctionField = 0 # Int64
# h1.sourcePortIdentity.clockIdentity = b'ABCDEFGH' # Octet[8]
# h1.sourcePortIdentity.portNumber = 1 # UInt16
# h1.sequenceId = 42 # UInt16
# h1.controlField = 0x05 # UInt8
# h1.logMessageInterval = 1 # Int8

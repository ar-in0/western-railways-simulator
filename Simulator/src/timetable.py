## How to represent a Rake-Cycle after parsing the timetable?
# Option1: Maintain a unique list of station objects per rake cycle. 
# Store arrival times in each station object. Too much repetition.
#
# Option2: A single set of station objects. 
# Currently using option2
# We want to plot the entire journey in a single day, and in particular, 
# during the peak hour
import pandas as pd
import re
from collections import defaultdict
import logging
from datetime import datetime
import time

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s]: %(message)s'
)
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

# to check column colour, need to create an authentication
# with google sheets. Downloading the file strips colour information.

# @oct24
# services have start end stations
# rake cycles have start end depot

SERVICE_ID_LEN = 5



class TimeTable:
    def __init__(self):
        # ground truth
        self.xlsxSheets = []
        # self.stationCol = None

        self.rakes = [Rake(i) for i in range(1,100)] # each rake has an id 1-100
        self.stations = {} # stationName: <Station>

        self.upServices = []
        self.downServices = []
        self.suburbanServices = None
        
        self.stationEvents = {} # station: StationEvent
        self.serviceChains = [] # created by following the serviceids across sheets

        # use the service chains to generate station events?
        # wont that reuire another parse of the serviceCols?
        # isnt it better for the service itself to contain station events?
        self.rakecycles = [] # needs timing info
        self.allCyclesWtt = [] # from wtt linked follow
        self.conflictingLinks = []
    
    # def generateRakeCyclePath(self, rakecycle):
    #     # Rakecycle contains the serviceIDs of a rake-link.
    #     # We simply find those services, get the stationpath with 
    #     # print(rakecycle)

    def storeOriginalACStates(self):
        """Store original AC states for reset capability"""
        self.originalACStates = {}
        for rc in self.rakecycles:
            if rc.rake:
                self.originalACStates[rc.linkName] = rc.rake.isAC
            # Also store service AC requirements
            for svc in rc.servicePath if rc.servicePath else []:
                self.originalACStates[f"svc_{svc.serviceId[0]}"] = svc.needsACRake

    def resetACStates(self):
        """Reset all AC states to original"""
        if not hasattr(self, 'originalACStates'):
            return
        
        for rc in self.rakecycles:
            if rc.rake and rc.linkName in self.originalACStates:
                rc.rake.isAC = self.originalACStates[rc.linkName]
            
            # Reset service AC requirements
            if rc.servicePath:
                for svc in rc.servicePath:
                    key = f"svc_{svc.serviceId[0]}"
                    if key in self.originalACStates:
                        svc.needsACRake = self.originalACStates[key]


    # We have a digraph, with nodes v repreented by 
    # Services, and edge (u,v) rep by `u.linkedTo = v`.
    # Rake-Links are CCs of the graph.
    # Our task is to identify the CCs given a set of Nodes
    # and Edges ie. G = (V, E)
    # Invariants for valid WTT:
    # - No cycles in CCs
    def makeRakeCyclePathsSV(self, services):
        '''
        Build rake-cycle paths by recursively following directed `linkedTo` chains.
        Each service node stores both `prev` and `next` links.
        '''
        idMap = {sid: s for s in services for sid in s.serviceId}
        adj = defaultdict(lambda: {'prev': None, 'next': None})

        # build directed links
        # ensure every linked node knows its prev and next
        # adj[sid] is a {prev, next} pair
        for sv in idMap.values():
            sid = sv.serviceId[0]
            # if its a terminal serviceId, say s
            # adj[s]['prev'] will be stored, because that node
            # will have had a linkedTo s (and therefore processed).
            # ---
            # ServiceIds that are independent (i.e. not part of a 
            # rake cycle, will be ignored. A rake cycle is a series
            # of 2 or more services.)
            if not sv.linkedTo: 
                continue
            try:
                nextId = int(str(sv.linkedTo).strip())
            except ValueError:
                nextId = str(sv.linkedTo).strip()

            # if this service is linked to 
            # a non-suburban service, we do
            # not count it as a rake cycle.
            if nextId not in idMap:
                continue
            
            # adj[sid]['prev'] is some id <A>
            # ----
            # when we have `sid` = A
            # adj[A]['next'] = sid, nextId = sid
            # adj[nextId] = adj[sid], ==>
            # adj[sid]['prev'] = A, as expected.
            #
            # In this way, prev and next for every linked serviceID
            # is stored in the adjacency list.
            adj[sid]['next'] = nextId  
            adj[nextId]['prev'] = sid

        visited = set()

        def followChain(sid, chain):
            if sid in visited or sid not in idMap:
                return
            visited.add(sid)
            chain.append(idMap[sid])
            nxt = adj[sid]['next']
            if nxt:
                followChain(nxt, chain)

        # We need to find chains - i.e. 
        # series of services that have no prev node
        # in the adjacency list.
        # skip sids until it reaches one that is an init
        #
        # BUG: 92010 is being detected as an intermediate node
        # since it is the linkedTo of service 92201, part of AP
        # But it is also the start of AA. 
        # The summary sheet says AP must end with 92201, but the wtt
        # says that 92201 is linked To 92010, causing an issue.
        # FIX: Use the summary sheet as source of truth for rake-cycle
        # plotting, but document the discrepancies with the WTT.
        # -- If a serviceID is both a linkedTo, and also a starting serviceID
        # from the summary, reconstruct its path from the summary.
        # -- If a serviceID of the rc.serviceIDs doesnt exist in the
        # allservices, that entire rake cycle is invalid. 
        # -- 
        for sid in idMap:
            if sid in visited:
                continue
            if adj[sid]['prev'] is not None:
                continue  # not a starting node
            if adj[sid]['next'] is None:
                continue  # isolated or terminal only
            
            # sid is a starting node.
            # now we follow its links
            chain = []
            followChain(sid, chain)
            if chain:
                # # print(chain[0])
                self.allCyclesWtt.append(chain)

        # print(f"Constructed {len(self.allCyclesWtt)} rake-cycle paths.")
        # for path in self.allCyclesWtt:
        #     # print(path[0])
    
    # rc: rake cycle
    def fixPath(self, rc):
        linkName = rc.linkName
        logger.info(f"Fixing serviceID path for rakecycle {linkName}")
        sid = rc.serviceIds[0]
        # print(sid)

        if rc.undefinedIds:
            logger.debug(f"Services {rc.undefinedIds} not defined in the WTT. Discarding the link.")
            rc.status = RakeLinkStatus.INVALID
            return []

        # is the first service of the wtt rakelink even defined?
        # Sids has every defined serviceID only. see generaterakecycles.
        # undefined by mentioned in syummary are ignored.
        # "For a given rc in the set of rakecycles created on the set of defined services, 
        # are there any services that are not defined"
        allServices = {str(s.serviceId[0]): s for s in self.suburbanServices}
        s = allServices.get(str(sid)) 
        assert(s) # due to the suburbanservices creation step earlier

        if any(str(sid) == str(sv.linkedTo) for sv in allServices.values()):
            logger.debug(f"Service {sid} appears as a linkedTo of another service in WTT. Possible mislink in rakecycle {linkName}.")
            logger.info("Treat summary as source of truth. Reconstruct path using the serviceIds in the summary")
            path = []
            # # print(rc.serviceIds)
            for id in rc.serviceIds:
                # # print(f"aha {id}")
                svc = allServices.get(str(id)) 
                assert(svc)
                path.append(svc)
            # logger.debug(path)
            return path

    # creates stationEvents
    def generateRakeCycles(self):
        self.suburbanServices.sort(
            key=lambda sv: (
                isinstance(sv.serviceId[0], int),  # False (0) for strings, True (1) for ints
                sv.serviceId[0]                    # then sort by the ID itself
            )
        )
        # for sv in self.suburbanServices:
            # print(sv)

        self.makeRakeCyclePathsSV(self.suburbanServices)
        # print(f"# rake links = {len(self.allCyclesWtt)}")

        for path in self.allCyclesWtt:
            # print(f"rakecycle starting with service {path[0].serviceId} has length = {len(path)}")
            sidpath = [s.serviceId[0] for s in path] # from summary
            # print(sidpath)

        # need to link the paths to the rake linkNames
        # wtt.rakeclcyes rc contain the linkname
        # and servicepath. Assign a path in allcycles to
        # rc.servicePath
        # rc.serviceIds contains the service path. [sids]
        # print("linking rake to path")
        invalid = []
        for rc in self.rakecycles:
            # print(rc.serviceIds)
            # print("---")
            # print(str(rc.serviceIds[0]))
            # print("---")
            for path in self.allCyclesWtt:
                # print(f"ahaha {str(path[0].serviceId[0])}")
                if str(rc.serviceIds[0]) == str(path[0].serviceId[0]):
                    # print(f"adding path of length {len(path)}")
                    rc.servicePath = path
                # else:
                #     logger.debug("Mismatch between wtt and summary init")
                #     logger.debug(f"summ: {str(rc.serviceIds[0])}, wtt: {str(path[0].serviceId[0])}")
            if not rc.servicePath:
                logger.debug(f"Link {rc.linkName}: Summ starts with: {str(rc.serviceIds[0])}, wtt starts with: {str(path[0].serviceId[0])}")
                # print(f"Issue with serviceIdpath: {rc.linkName}") # every rakecycle must be assigned its path by the end.
                logger.warning(f"Unable to match rakelink {rc.linkName} to a wtt-derived service-path. Fixing...")
                fixedPath = self.fixPath(rc)
                if rc.status == RakeLinkStatus.INVALID:
                    # delete the RakeCycle
                    invalid.append(rc)
                    # self.rakecycles.remove(rc)
                    # continue
                rc.servicePath = fixedPath

        for rc in invalid:
            self.rakecycles.remove(rc)

        logger.debug(f"# Rakecycles after fixing: {len(self.rakecycles)}")

        # validate paths:
        # in class rakecycle, serviceIDs[] reps the service serires
        # parsed from the summary.
        # At this point, we have a set of 
        # The rakecycles obtained from wtt traversal should exactly match
        # those obtained from the summary parse. Rakecycles that do not 
        # match must be inspected seperately
        self.validateRakeCycles()
        
        logger.debug(f"After fixup and validation, we have {len(self.rakecycles)} consistent cycles.")
        # for rc in self.rakecycles:
            # print(rc)
        
        # Then for every service in every rakecycle, parse the stationcol 
        # to extract timings and create StationEvents.
        # services not in the valid rakecycles will
        # not have events. 
        for rc in self.rakecycles:
            # print(rc.servicePath)
            if not rc.servicePath:
                # print(rc)
                pass
            for svc in rc.servicePath:
                svc.generateStationEvents()
                assert(svc.events)
                svc.initStation = self.stations[svc.events[0].atStation]   
                svc.finalStation = self.stations[svc.events[-1].atStation]

                # calculate service distance
                svc.computeLengthKm()
                rc.lengthKm += svc.lengthKm
            print(f"Length of {rc.linkName} = {rc.lengthKm} Km")

        # assign rakes to rakecycles
        self.assignRakes()

        # for rc in self.rakecycles:
        #     self.generateRakeCyclePath(rc) 
    def assignRakes(self):
        for i, rc in enumerate(self.rakecycles):
            rake = Rake(i)
            for svc in rc.servicePath:
                # make half of them AC
                # if i < len(self.rakecycles)/2 + 10:
                #     svc.needsACRake = True
                if svc.needsACRake:
                    rake.isAC = True
                    break
                if svc.rakeSizeReq:
                    rake.rakeSize = svc.rakeSizeReq
                    break
            rc.rake = rake


    # Summarizes the wtt
    # 1. Total # services
    # 2. Services in up direction
    # 3. Services in down direction
    # 4. num AC services
    # 5. In a certain time-period, how many services runnning?
    def printStatistics(self):
        pass

    def validateRakeCycles(self):
        cycles = self.rakecycles
        logger.debug("Removing inexact rakecycle matches.")
        for rc in cycles:
            summaryPath = rc.serviceIds
            wttPath = [svc.serviceId[0] for svc in rc.servicePath]

            # check reduced path1
            summaryPathRed1 = summaryPath[:-2]

            # if theres a full match, GREAT.
            # if not a full match, if theres an exact partial match 
            # and the non-matches are ety-style sids, Also GREAT.

            if wttPath != summaryPath:
                # print("Inexact summary link and wtt link")
                # print(f"{rc.linkName} wttpath: {wttPath}")
                # print(f"{rc.linkName} summarypath: {summaryPath}")
                if summaryPath[:-1] == wttPath:
                    if "ETY" in str(summaryPath[-1]):
                        continue
                else:
                    if summaryPath[:-2] == wttPath:
                        if "ETY" in str(summaryPathRed1[-1]) and "ETY" in str(summaryPath[-1]):
                            continue
                self.conflictingLinks.append((rc, wttPath))
                    
        for rc in self.conflictingLinks:
            self.rakecycles.remove(rc[0])

class Rake:
    '''Physical rake specifications.'''
    def __init__(self, rakeId):
        self.rakeId = rakeId
        self.isAC = False
        self.rakeSize = 12 # How many cars in this rake?
        self.velocity = 1 # can make it a linear model
        self.assignedToLink = None  # which rake-cycle is it used for?

    def __repr__(self):
        return f"<Rake {self.rakeId} ({'AC' if self.isAC else 'NON-AC'}, {self.rakeSize}-car)>"

class RakeCycle:
    # A rake cycle is the set of stations that a particular rake covers in a 
    # day, aka Rake-Link
    def __init__(self, linkName): # linkName comes from summary sheet.
        self.rake = None
        self.status = RakeLinkStatus.VALID

        # From parsing summary sheet.
        self.linkName = linkName  # A, B, C etc.
        # self.services = {}       # serviceID: Service
        self.serviceIds = [] # list of serviceIDs that implement this link
        self.undefinedIds = []
        # we want the summary sheet and the wtt to agree always
        self.startDepot = None
        self.endDepot = None

        # for a detailed visualization later.
        # generateRakeCyclePath()

        # from the service list, we can generate all
        # the stationevents associated with a rakecycle.
        # so a rakecycle will have:
        # {st1: [], st2: [], ...}
        # self.path = {} # {stationID: [StationEvent]}
        
        # [list of services in path]. Service contains stationevents.
        self.servicePath = None

        self.render = True # render each rakecycle
        self.lengthKm = 0 # updated during generatecycles

    
    def __repr__(self):
        rake_str = self.rake.rakeId if self.rake else 'Unassigned'
        n_services = len(self.servicePath)
        start = self.servicePath[0].events[0].atStation if self.servicePath else '?'
        end = self.servicePath[-1].events[-1].atStation if self.servicePath else '?'
        # start = self.startDepot if self.startDepot else '?'
        # end = self.endDepot if self.endDepot else '?'


        return f"<RakeCycle {self.linkName} ({n_services} services, {self.lengthKm}Km) {start}->{end}>"
    
# const
# The service details must be stored first. After that, 
# a row-wise traversal is done to assign events (which are tarrival,depart pairs)
# Service does not store any timing info!??
# Pick a service column
# Then, for every station row check:
# - is this station accesed? 
# --> If yes, append a refernce to the station to service.stationpath
# --> if no, 

from enum import Enum

class RakeLinkStatus(Enum):
    VALID = 'valid'
    INVALID = 'invalid'

# initially we onl handle regular suburban trains
# excluding dahanu road 
# services
class ServiceType(Enum):
    REGULAR = 'regular'
    STABLING = 'stabling'
    MULTI_SERVICE = 'multi-service'

class ServiceZone(Enum):
    SUBURBAN = 'suburban'
    CENTRAL = 'central'

class Direction(Enum):
    UP = 'up'
    DOWN = 'down'

class Day(Enum):
    MONDAY = 'monday'
    TUESDAY = 'tuesday'
    WEDNESDAY = 'wednesday'
    THURSDAY = 'thursday'
    FRIDAY = 'friday'
    SATURDAY = 'saturday'
    SUNDAY = 'sunday'

class Line(Enum):
    THROUGH = 'through/fast'
    LOCAL = 'local/slow'

class Service:
    '''Purely what can be extracted from a single column'''
    def __init__(self, type: ServiceType):
        self.rawServiceCol = None
        self.type = type # regular, stabling, multi-service
        self.zone = None # western, central
        self.serviceId = None # a list
        self.direction = None # UP (VR->CCG) or DOWN (CCG to VR)
        self.line = None #Through (fast) or Local (L)

        self.rakeLinkName = None
        self.rakeSizeReq = None # 15 is default?, 12 is specified via "12 CAR", but what are blanks?
        self.needsACRake = False

        self.initStation = None
        # service id after reversal at last station. 
        # Will be used to generate the rake cycle.
        # i.e. the next service integer ID. Will be in
        # the up timetable
        self.linkedTo = None 
        self.finalStation = None

        self.events = [] # [StationEvents in chronological order]

        # by default each service is active each day
        # AC services have a date restriction
        # "multi-service" services have date restrictions.
        self.activeDates = set(Day) 
        self.render = True
        
        # self.name = None
    
    def checkStartStationConstraint(self, qq):
        if not qq.startStation:
            return
        
        start = qq.startStation
        print(self.events)
        print(self)
        first = self.events[0].atStation

        t_first = self.events[0].atTime
        t_lower, t_upper = qq.inTimePeriod # minutes
        print(first)
        print(start)

        if first == start:
            if not (t_lower <= t_first <= t_upper):
                self.render = self.render and False
        else:
            self.render = self.render and False
        
    def checkEndStationConstraint(self, qq):
        if not qq.endStation:
            return
        
        end = qq.endStation
        last = self.events[-1].atStation
        t_last = self.events[-1].atTime
        t_lower, t_upper = qq.inTimePeriod

        if last == end:
            if not (t_lower <= t_last <= t_upper):
                self.render = self.render and False
        else:
            self.render = self.render and False

    def checkDirectionConstraint(self, qq):
        dir = qq.inDirection
        if not dir:
            return
        
        dirMatch = False
        # print(f"dir: {qq.inDirection}")
        for d in qq.inDirection:
            if d == "UP" and self.direction == Direction.UP:
                dirMatch = True
                break
            elif d == "DOWN" and self.direction == Direction.DOWN:
                dirMatch = True
                break
        
        if not dirMatch:
            self.render = self.render and False

    def checkACConstraint(self, qq):
        mode = qq.ac
        if not mode or mode == "all":
            return
        
        if mode == "ac" and not self.needsACRake:
            self.render = self.render and False
        elif mode == "nonac" and self.needsACRake:
            self.render = self.render and False

    def checkPassingThroughConstraint(self, qq):
        qPassingStns = [s.upper() for s in qq.passingThrough] if qq.passingThrough else []
        if not qPassingStns:
            return # no filter
        
        # map stations in servicepath to times
        stnMapTimes = {}
        for e in self.events:
            if e.atStation not in stnMapTimes:
                stnMapTimes[e.atStation] = []
            stnMapTimes[e.atStation].append(e.atTime)

        for st in qPassingStns:
            # if even one query station is not passed by the
            # service, return
            if st not in stnMapTimes:
                self.render = self.render and False
                return
            
            # this service passes through this query station
            # check if it occurs in the given time interval
            t = stnMapTimes[st][-1]
            t_lower, t_upper = qq.inTimePeriod
            if not (t_lower <= t <= t_upper):
                self.render = self.render and False
                return
        
        # if here, the service satisfies the constraint
        # render it.

    def computeLengthKm(self):
        l = 0
        dprev = TimeTableParser.distanceMap[self.events[0].atStation]
        for e in self.events[1:]:
            stName = e.atStation
            dCCGKm = TimeTableParser.distanceMap[stName]
            d = abs(dprev - dCCGKm)
            l += d
            dprev = dCCGKm
        # assert(l > 0)
        self.lengthKm = l

    def generateStationEvents(self):
        sheet = None
        if self.direction == Direction.UP:
            sheet = TimeTableParser.wttSheets[0]
        else:
            sheet = TimeTableParser.wttSheets[1]

        stName = None
        serviceCol = self.rawServiceCol
        # print(serviceCol)
        for rowIdx, cell in serviceCol.items():
            match = TimeTableParser.rTimePattern.search(str(cell))
            if match:
                tCell = match.group(0)
                stName= sheet.iat[rowIdx, 0]
                # # print(stName)
                # this can be made better
                if pd.isna(stName) or not str(stName).strip():
                    # check row above
                    stName = sheet.iat[rowIdx - 1, 0]
                    if pd.isna(stName) or not str(stName).strip():
                        stName = sheet.iat[rowIdx - 2, 0]
                # stName = str(self.stationCol.iloc[rowIdx]).strip().upper()
                if str(stName).strip() == "M'BAI CENTRAL (L)":
                    # hack special case. 
                    # make names identical in wtt is the right solution
                    stName = "M'BAI CENTRAL(L)" 
                if str(stName).strip().upper() == "KANDIVLI":
                    # hack special case. 
                    # make names identical in wtt is the right solution
                    stName = "KANDIVALI" 
                if str(stName).strip() in TimeTableParser.stations.keys():
                    station = TimeTableParser.stations[str(stName).strip()]
                    # # print(f"Last station from time: {str(stName).strip()}")
                    # print(f"Got valid station from time: {station.name}")
                elif "REVERSED" in str(stName).upper():
                    # The timing in the reversed as belongs to the last station with
                    # a valid time, not the station above
                    # print("reversal")
                    # check row above
                    stName= sheet.iat[rowIdx - 1, 0]
                    if pd.isna(stName) or not str(stName).strip():
                        stName = sheet.iat[rowIdx - 2, 0]
                    
                    stName = self.events[-1].atStation
                
                stName = stName.strip().upper()
                
                # check arrival and departure
                # at a time cell, is it near an A or D cell.
                # if so, there is some dwell.
                # print(sheet.iat[rowIdx, 1])
                # isDTime = True if sheet.iat[rowIdx, 1] == "D" else False
                isATime = True if sheet.iat[rowIdx, 1] == "A" else False

                # assuming A always before D
                if isATime:
                    tArr = str(tCell).strip()
                    e1 = StationEvent(stName, self, tArr, EventType.ARRIVAL)
                    # assert next time is a D time
                    isDTime = True if sheet.iat[rowIdx+1, 1] == "D" else False
                    self.events.append(e1)
                    TimeTableParser.eventsByStationMap[stName].append(e1)
                    # # print(sheet.iat[rowIdx+1, 1])
                    if isDTime:
                        tDep = str(serviceCol.iloc[rowIdx + 1]).strip()
                        # print(tDep)
                        # assert tDep is a time
                        if TimeTableParser.rTimePattern.match(tDep):
                            # print("boom")
                            e2 = StationEvent(stName, self, tDep, EventType.DEPARTURE)
                            self.events.append(e2)
                            TimeTableParser.eventsByStationMap[stName].append(e2)
                    else:
                        # probably the last station
                        # nothing to do
                        pass
                else:
                    # time at a non-A spot, single event
                    # arrival-departure events will be with a single time.
                    # we assume the gap between arrival departure is small, 
                    # but arrival time is specified in the wtt.
                    time = str(tCell).strip()
                    e = StationEvent(stName, self, time, EventType.ARRIVAL)
                    self.events.append(e)
                    TimeTableParser.eventsByStationMap[stName].append(e)

        # print(f"For service {self.serviceId}, events are:")
        # for ev in self.events:
        #     print(f"{ev.atStation}: {ev.atTime}")
                    
    def __repr__(self):
        sid = ','.join(str(s) for s in self.serviceId) if self.serviceId else 'None'
        dirn = self.direction.name if self.direction else 'NA'
        zone = self.zone.name if self.zone else 'NA'
        ac = 'AC' if self.needsACRake else 'NON-AC'
        rake = f"{self.rakeSizeReq}-CAR" if self.rakeSizeReq else '?'
        init = self.initStation.name if self.initStation else '?'
        final = self.finalStation.name if self.finalStation else '?'
        linked = self.linkedTo if self.linkedTo else 'None'

        return f"<Service {sid} ({dirn}, {zone}, {ac}, {rake}) {init}->{final} linked:{linked}>"

    def getLastStation(self):
        return self.stationPath[-1]

    def getFirstStation(self):
        return self.stationPath[0]
    
class EventType(Enum):
    ARRIVAL = 'ARRIVAL',
    DEPARTURE = 'DEPARTURE'

class StationEvent:
    def __init__(self, st, sv, time, type):
        self.atStation = st
        self.ofService = sv
        self.atTime = self._timeToMinutes(time)

        self.platform = None
        self.eType = None
        self.render = True
    
    def _timeToMinutes(self, time_str):
        '''Convert time string to minutes since midnight, with wrap-around.'''
        if not time_str:
            return None
        try:
            t = datetime.strptime(time_str.strip(), "%H:%M:%S")
        except:
            try:
                t = datetime.strptime(time_str.strip(), "%H:%M")
            except:
                return None
        
        minutes = t.hour * 60 + t.minute + t.second / 60
        if minutes < 165:  # 2:45 AM wrap-around
            minutes += 1440
        return minutes


# Activity at a station is dynamic with time
# The activity is studied to generate rake-cycles
# which is a sequence of station ids for every rake id.
class Station:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.large = False # all caps/lowercase
        self.rakeHoldingCapacity = None # max rakes at this station at any given time.
        self.events = {} # {rakelinkName: [stationEvent]}

# Create a TimeTable object. This is then plotted
# via plotly-dash.
# Algo:
# 1. Create a list of every available service. (each service contains list of stations)
# 2. Pick a rake id. For that rake, begin 
class TimeTableParser:
    rCentralRailwaysPattern = re.compile(r'^[Cc]\.\s*[Rr][Ll][Yy]\.?$')
    rTimePattern = re.compile(
        r'(?:\d{1,2}/\d{1,2}/\d{2,4}\s+)?'   # optional date prefix
        r'(?P<time>[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$'  # capture only time
    )
    rServiceIDPattern = re.compile(r'^\s*\d{5}(?:\b.*)?$', re.IGNORECASE)
    rLinkNamePattern = re.compile(r'^\s*([A-Z]{1,2})\s*(?:\u2020)?\s*$', re.UNICODE) # only match A AK with dagger, i.e. start links
    rEtyPattern = re.compile(r'\bETY\s*\d+\b', re.IGNORECASE)

    # extracted from the WTT parse
    # Finally need store a single source of truth
    # from both the summary and the WTT, so hopefully both match.
    # @290ct: not used
    rakeLinkNames = [] 

    wttSheets = [] # upsheet, downsheet, summary sheets

    # From https://bhaaratham.com/list-of-stations-mumbai-local-train/
    distanceMap = {
        "CHURCHGATE": 0, "MARINE LINES": 2, "CHARNI ROAD": 3, "GRANT ROAD": 4,
        "M'BAI CENTRAL(L)": 5, "MAHALAKSHMI": 6, "LOWER PAREL": 8, "PRABHADEVI": 9,
        "DADAR": 11, "MATUNGA ROAD": 11.5, "MAHIM JN.": 12, "BANDRA": 15,
        "KHAR ROAD": 17, "SANTA CRUZ": 18, "VILE PARLE": 20, "ANDHERI": 22,
        "JOGESHWARI": 24, "RAM MANDIR": 25.5, "GOREGAON": 27, "MALAD": 30, "KANDIVALI": 32,
        "BORIVALI": 34, "DAHISAR": 37, "MIRA ROAD": 40, "BHAYANDAR": 44,
        "NAIGAON": 48, "VASAI ROAD": 52, "NALLASOPARA": 56, "VIRAR": 60
    }

    eventsByStationMap = defaultdict(list)

    def __init__(self, fpWttXlsx=None, fpWttSummaryXlsx=None):
        self.wtt = TimeTable()
        self.stationCol = None # df column with stations

        # if the req comes from a local test
        # i.e. python3 timetable.py
        if fpWttSummaryXlsx and fpWttXlsx:
            self.xlsxToDf(fpWttXlsx)
            self.registerStations()
            self.registerServices()

            # get timing information too 
            # WTT services must be fully populated 
            # before starting the summary-sheet parse.


            # parse summary sheet
            # generate rakelink summary
            self.parseWttSummary(fpWttSummaryXlsx)


            self.wtt.suburbanServices = self.isolateSuburbanServices()
        # # print(self.suburbanServices)
        # for s in self.suburbanServices:
        #     # print(s.serviceId)
    @classmethod
    def fromFileObjects(cls, wttFileObj, summaryFileObj):
        '''Create TimeTableParser from BytesIO objects for uploaded files'''
        instance = cls()
        start = time.time()
        instance.xlsxToDfFromFileObj(wttFileObj)
        instance.registerStations()
        end = time.time()

        # this can be triggered when the 
        # summary sheet is uploaded
        instance.registerServices()
        print(f"time in: {end - start}")
        instance.parseWttSummaryFromFileObj(summaryFileObj) # creates rakecycles without timing info
        instance.wtt.suburbanServices = instance.isolateSuburbanServices()
        return instance

    def xlsxToDfFromFileObj(self, fileObj):
        '''Parse Excel from file object instead of path'''
        xlsx = pd.ExcelFile(fileObj)
        for sheet in xlsx.sheet_names:
            df = xlsx.parse(sheet, skiprows=4).dropna(axis=1, how='all')
            TimeTableParser.wttSheets.append(df)
            
        self.upSheet = TimeTableParser.wttSheets[0]
        self.downSheet = TimeTableParser.wttSheets[1]

    def parseWttSummaryFromFileObj(self, fileObj):
        '''Parse summary Excel from file object instead of path'''
        xlsx = pd.ExcelFile(fileObj)
        summarySheet = xlsx.sheet_names[0]
        self.wttSummarySheet = xlsx.parse(summarySheet, skiprows=2).dropna(axis=0, how="all")
        self.parseRakeLinks(self.wttSummarySheet)
    
    def isolateSuburbanServices(self):
        suburbanIds = set()
        # print("Updating suburban")
        seen, repeated = set(), set()
        for rc in self.wtt.rakecycles:
            # print(rc.serviceIds)
            suburbanIds.update(rc.serviceIds)
            s = set(rc.serviceIds)
            repeated |= seen & s
            seen |= s
        # print(repeated)
        
        suburbanServices = []
        for s in (self.wtt.upServices + self.wtt.downServices):
            if any(sid in suburbanIds for sid in s.serviceId):
                suburbanServices.append(s)

        print(f"\nSuburban services identified: {len(suburbanServices)} / {len(self.wtt.upServices) + len(self.wtt.downServices)}")
        return suburbanServices

    # timetable.py -> class TimeTableParser
    def parseRakeLinks(self, sheet):
        allServices = self.wtt.upServices + self.wtt.downServices
        sheet = sheet.reset_index(drop=True)

        for i in range(len(sheet)):
            sIDRow = sheet.iloc[i]

            # check for linkname
            if pd.isna(sIDRow.iloc[1]):
                continue

            linkName = str(sIDRow.iloc[1]).strip().upper()
            if not TimeTableParser.rLinkNamePattern.match(linkName):
                continue

            # Identify the speed row (FAST/SLOW is 2 rows below Service IDs)
            lineRow = None
            if i + 2 < len(sheet):
                lineRow = sheet.iloc[i + 2]

            # collect all valid service IDs and their corresponding speed labels
            # We store them as pairs to maintain the column association
            service_entries = []
            
            # Use enumerate to keep track of column indices relative to iloc[2:]
            for col_offset, cell in enumerate(sIDRow.iloc[2:]):
                if pd.isna(cell):
                    continue
                cell = str(cell)
                
                if TimeTableParser.isServiceID(cell):
                    # --- Existing extraction logic ---
                    matchEty = TimeTableParser.rEtyPattern.search(cell)
                    if matchEty:
                        sid_val = matchEty.group(0)
                    else:
                        digit_match = re.search(r'\d+', cell)
                        sid_val = int(digit_match.group()) if digit_match else cell

                    # ---  line Extraction Logic ---
                    line_label = None
                    if lineRow is not None:
                        # Absolute column index is col_offset + 2
                        raw_line = lineRow.iloc[col_offset + 2]
                        if not pd.isna(raw_line):
                            val = str(raw_line).strip()
                            # Mark with label if match, else store raw string
                            if val.upper() in ["FAST", "SLOW"]:
                                line_label = val.upper()
                            else:
                                if "FAST" in val.upper() or "SLOW" in val.upper():
                                    line_label = val
                        
                    
                    service_entries.append((sid_val, line_label))

            if not service_entries:
                continue

            rc = RakeCycle(linkName)

            for sid, speed in service_entries:
                rc.serviceIds.append(sid)
                # Match with Service objects (casting to string for robust comparison)
                service = next((s for s in allServices if str(sid) in str(s.serviceId)), None)
                if service:
                    service.linkName = linkName
                    service.speed = speed # Assign the extracted speed label
                else:
                    rc.undefinedIds.append((linkName, sid))

            self.wtt.rakecycles.append(rc)

        # summary (Logic remains the same as your original)
        if 'rc' in locals() and rc.undefinedIds:
            print(f"\n{len(rc.undefinedIds)} service IDs from summary sheet not found in detailed WTT:")
            for linkName, sid in rc.undefinedIds:
                print(f" ** Link {linkName}: Service {sid}")
        elif 'rc' in locals():
            print("\nAll rake link service IDs successfully matched with WTT services.")
    
    def parseWttSummary(self, filePathXlsx):
        xlsx = pd.ExcelFile(filePathXlsx)
        summarySheet = xlsx.sheet_names[0]
        self.wttSummarySheet = xlsx.parse(summarySheet, skiprows=2).dropna(axis=0, how="all") # drop fully blank rows
        
        self.parseRakeLinks(self.wttSummarySheet)

    def xlsxToDf(self, filePathXlsx):
        xlsx = pd.ExcelFile(filePathXlsx)
        for sheet in xlsx.sheet_names:
            # First row is blank, followed by the station row # onwards
            # with skipped=4. skipped=5 removes the extra white row above the main content.
            df = xlsx.parse(sheet, skiprows=4).dropna(axis=1, how='all')
            TimeTableParser.wttSheets.append(df)
            # remove fully blank columns
            
        self.upSheet = TimeTableParser.wttSheets[0]
        self.downSheet = TimeTableParser.wttSheets[1]
    
    # always use cleancol before working with a column
    def cleanCol(self, sheet, colIdx):
        '''Return the column as-is unless it is entirely NaN or whitespace.'''
        clean = sheet.iloc[:, colIdx].astype(str)

        # Check if all entries are NaN or whitespace (after conversion to str)
        if clean.isna().all() or clean.str.fullmatch(r'(nan|\s*)', na=False).all():
            return pd.Series(dtype=str)

        # if (colIdx == 0):
        #     mask =  clean.str.fullmatch(r'\s*')
        #     # invert mask to keep non-blank rows
        #     clean = clean[~mask]

        return clean

    def registerStations(self):
        '''Create an object corresponding to every station on the network'''
        sheet = self.upSheet # a dataframe
        self.stationCol = sheet.iloc[:, 0]
        # self.stationCol = self.cleanCol(sheet, 0) # 0 column index of station
        # # print(stationCol)
        # # print((self.stationCol[1:-8])) 

        for idx, rawVal in enumerate(self.stationCol[1:-8]): # to skip the linkage line + nans
            if pd.isna(rawVal):
                continue
            stName = str(rawVal).strip()
            if not stName:
                continue
            
            st = Station(idx, stName.upper())
            # print(f"Registering station {st.name}, idx {st.id}")
            self.wtt.stations[st.name] = st 
            
            st.dCCGkm = TimeTableParser.distanceMap[st.name]
            # print(f"station {st.name} distance from CCG: {st.dCCGkm}")
        
        # create station map
        TimeTableParser.stationMap = {
            "BDTS": self.wtt.stations["BANDRA"],
            "BA": self.wtt.stations["BANDRA"],
            "MM": self.wtt.stations["MAHIM JN."],
            "ADH": self.wtt.stations["ANDHERI"],
            "KILE": self.wtt.stations["KANDIVALI"],
            "BSR": self.wtt.stations["BHAYANDAR"],
            "DDR": self.wtt.stations["DADAR"],
            "VR": self.wtt.stations["VIRAR"],
            "BVI": self.wtt.stations["BORIVALI"],
            "CSTM": Station(43, "CHATTRAPATI SHIVAJI MAHARAJ TERMINUS"),
            "CSMT": Station(44, "CHATTRAPATI SHIVAJI MAHARAJ TERMINUS"),
            "PNVL": Station(45, "PANVEL"),
            "MX": self.wtt.stations["MAHALAKSHMI"]
        }

        TimeTableParser.stations = self.wtt.stations

    # First station with a valid time
    # "EX ..."
    # else First station in Stations i.e. VIRAR
    def extractInitStation(self, serviceCol, sheet):
        '''Determines the first arrival station in the service path.
        serviceCol: pandas.Series
        sheet: pandas.Dataframe'''
        # # print(serviceCol)

        # for every column:
        # stop at the first time string
        # in that row, look leftwards for a station name.
        # also check for A, D
        # if station name found, that station is the init station.
        ## if name in self.wtt.stations.keys(): its a starting time
        stationName = None
        for rowIdx, cell in serviceCol.items():
            if TimeTableParser.rTimePattern.match(cell):
                stationName = sheet.iat[rowIdx, 0]
                # row = sheet.iloc[rowIdx, :].astype(str)
                # stationName = row.iloc[0]
                # # print(f"{stationName}: {cell}")

                if pd.isna(stationName) or not str(stationName).strip():
                    # check row above if possible
                    if rowIdx > 0:
                        stationName = sheet.iat[rowIdx - 1, 0]
                break

        if pd.isna(stationName) or not str(stationName).strip():
            raise ValueError(f"Invalid station name near row {rowIdx}")
        
        # # print(self.wtt.stations.keys())
        if stationName == "M'BAI CENTRAL (L)":
            # hack special case. 
            # make names identical in wtt is the right solution
            stationName = "M'BAI CENTRAL(L)" 
        
        if stationName.upper() == "KANDIVLI":
            stationName = "KANDIVALI"

        station = self.wtt.stations[stationName.strip().upper()]
        assert(station)
        return station
        
    def extractFinalStation(self, serviceCol, sheet):
        # ARRL., Arr, ARR
        # last station with a timing
        # last station in stations, i.e. CCG

        # If some cell contains "Arrl./arrl/ARRL/ARR":
        # check for a name in stationmap and a time in nearby cells
        # "nearby cells": current cell, cell above, cell below.
        # (if the stationmap doesnt contain the string, # print it)

        # else:
        # return the station associated with the last time
        abbrStations = TimeTableParser.stationMap.keys()
        station = None
        arrlRowIdx = None

        # Find the "ARR" / "ARRL." marker first
        for rowIdx, cell in serviceCol.items():
            cellStr = str(cell).strip().upper()
            if re.search(r'\bARRL?\.?\b', cellStr, flags=re.IGNORECASE):
                # # print("found arr")
                arrlRowIdx = rowIdx
                break

        # If arrl not found:
        if not arrlRowIdx:
            # arrl station not explicitly written, 
            # use the station with last mentioned timing
            for rowIdx in reversed(serviceCol.index):
                cell = str(serviceCol.iloc[rowIdx]).strip()
                if TimeTableParser.rTimePattern.match(cell):
                    stName= sheet.iat[rowIdx, 0]
                    # # print(stName)
                    # this can be made better
                    if pd.isna(stName) or not str(stName).strip():
                        # check row above
                        stName = sheet.iat[rowIdx - 1, 0]
                        if pd.isna(stName) or not str(stName).strip():
                            stName = sheet.iat[rowIdx - 2, 0]
                    # stName = str(self.stationCol.iloc[rowIdx]).strip().upper()
                    if str(stName).strip() == "M'BAI CENTRAL (L)":
                        # hack special case. 
                        # make names identical in wtt is the right solution
                        stName = "M'BAI CENTRAL(L)" 
                    if str(stName).strip().upper() == "KANDIVLI":
                        # hack special case. 
                        # make names identical in wtt is the right solution
                        stName = "KANDIVALI" 
                    if str(stName).strip() in self.wtt.stations.keys():
                        station = self.wtt.stations[str(stName).strip()]
                        # print(f"Last station from time: {str(stName).strip()}")
                        return station
                    elif "REVERSED" in str(stName).upper():
                        # # print("reversal")
                        # check row above
                        stName= sheet.iat[rowIdx - 1, 0]
                        if pd.isna(stName) or not str(stName).strip():
                            stName = sheet.iat[rowIdx - 2, 0]
                        station = self.wtt.stations[str(stName).strip()]
                        # print(f"Last station from time,: {str(stName).strip()}")
                        return station

            # print("Could not determine final station (no ARRL or valid time)")
            return station
        
        # arrl found, now look in nearby cells for a station
        nearbyRows = [arrlRowIdx]
        if arrlRowIdx > 0:
            nearbyRows.append(arrlRowIdx - 1)
        if arrlRowIdx < len(serviceCol) - 1:
            nearbyRows.append(arrlRowIdx + 1)

        stationName = None
        for r in nearbyRows:
            cellVal = str(serviceCol.iloc[r]).strip().upper()
            # print(f"'{cellVal}'")
            if not cellVal or cellVal == 'NAN':
                continue

            # does it contain a station abbreviation?
            for stKey in abbrStations:
                # allow substring match (e.g. "CCG ARR." -> finds "CCG")
                if stKey in cellVal:
                    stationName = stKey
                    break

            if stationName:
                # found a valid station in/near the ARRL region
                # print(f"found stationname {stationName} from row {r}: {cellVal}")
                station = TimeTableParser.stationMap[stationName]
                # # print(station)
                return station

            # if not found, # print the cell for debugging
            # print(f"No station match near ARRL at row {r}: {cellVal}")
        

    def extractInitialDepot(self, serviceID):
        '''Every service must start at some yard/carshed. These
        are specified in the WTT-Summary Sheet.'''
        pass
    
    def extractLinkedToNext(self, serviceCol, direction):
        '''Find the linked service (if any) following a 'Reversed as' entry.'''
        # dropNa
        serviceCol = serviceCol.dropna()
        mask = self.stationCol.str.contains("Reversed as", case=False, na=False)
        match = self.stationCol[mask]

        if match.empty:
            return None

        rowIdx = match.index[0]
        # print(rowIdx)
        # # print(serviceCol)

        # Guard
        if rowIdx not in serviceCol.index:
            return None

        # for lower sheet, the idx are idx -1, idx
        if (direction == Direction.UP):
            depTime = serviceCol.loc[rowIdx]
            linkedService = serviceCol.loc[rowIdx + 1]
        else:
            depTime = serviceCol.loc[rowIdx -1]
            linkedService = serviceCol.loc[rowIdx]


        # Convert safely, handle NaN/None/float cases
        if pd.isna(linkedService) or pd.isna(depTime):
            return None

        depTime = str(depTime).strip()
        linkedService = str(linkedService).strip()

        # Skip empty, non-sid
        match = linkedService.isdigit() and len(linkedService) == SERVICE_ID_LEN
        if not depTime or depTime.lower() == "nan" or not linkedService or linkedService.lower() == "nan" or not match:
            linkedService = None

        # print(f"Linked to: {linkedService} at {depTime}")
        return linkedService

    def determineLineType(self, serviceCol, sheet):
        '''Determine if service is Through (fast) or Local (slow) based on stations skipped'''
        # Count stations with timing information vs total stations
        timed_stations = 0
        total_stations = 0
        
        for rowIdx, cell in serviceCol.items():
            if TimeTableParser.rTimePattern.match(cell):
                timed_stations += 1
            total_stations += 1
        
        # If service stops at fewer than 60% of stations, consider it Through (fast)
        if total_stations > 0 and (timed_stations / total_stations) < 0.4:
            return Line.THROUGH
        return Line.LOCAL
    
    @staticmethod
    def isServiceID(cell): # cell must be str
        # if empty, return False
        if not cell or cell.strip().lower() == "nan":
            return False
        # service IDs may be ETY <integer>
        # or 5-long positive integer + <some optional text>
        return bool(
            TimeTableParser.rServiceIDPattern.match(cell) or
            TimeTableParser.rEtyPattern.search(cell)
            )
    
    # @staticmethod
    def isRakeLinkName(cell):
        if not cell or cell.strip().lower() == "nan":
            return False
        
        # if 2 letter, but in the stationmap, its not a linkname
        # but its the 
        # Currently, matches only AB with dagger so the stationmap check is
        # redundant.
        match = TimeTableParser.rLinkNamePattern.match(cell)
        if match:
            # if match.group(0) in TimeTableParser.stationMap:
            #     return False
            # else:
            return True # 2 letter string not in the station map

    @staticmethod
    def extractServiceHeader(serviceCol):
        '''Extract service ID and Rake size and zone requirement'''
        # Isolate the 5-6 rows below row# of stations in the various columns
        # Then parse again, 
        # Any integer is the service id 
        # if more integers, process them in a second pass
        # as special services. (where you consider dates, etc.)
        idRegion =  serviceCol[:6]
        # # print(idRegion)
        ids = []
        rakeSize = 15 # default size
        zone = None
        for cell in idRegion: # cell contents are always str
            cell = cell.strip()
            if TimeTableParser.rCentralRailwaysPattern.match(cell):
                zone = ServiceZone.CENTRAL

            # return true 
            if TimeTableParser.isServiceID(cell):
                # numeric or ETY-style
                matchEty = TimeTableParser.rEtyPattern.search(cell)
                if matchEty:
                    ids.append(matchEty.group(0))  # store the ETY token as string
                else:
                    ids.append(int(re.search(r'\d+', cell).group())) # extract the integer ex 93232 L/SPL
                    if (cell.startswith("9")):
                        zone = ServiceZone.SUBURBAN
            
            # get the linkName
            # Assume WTT linknames are inaccurate - retrieve from the summary sheet.
            linkName = None
            # if TimeTableParser.isRakeLinkName(cell): # XX, and optionally a cross
            #     match = TimeTableParser.rLinkNamePattern.search(cell) # extract the XX
            #     if match:
            #         linkName = match.group(1)
            #         # print(f"Rake Link Name: {linkName}")
            #         # record it
            #         TimeTableParser.rakeLinkNames.append(linkName)

            # check for CAR
            if "CAR" in cell.upper():
                # # print(cell)
                match = re.search(r'(12|15|20|10)\s*CAR', cell, flags=re.IGNORECASE)
                assert match is not None
                rakeSize = int(match.group(1))

        return ids, rakeSize, zone, linkName

    @staticmethod
    def extractACRequirement(serviceCol):
        isAC = -1
        for cell in serviceCol:
            cell = cell.strip()
            if (isAC == 1): return True  
            if ("Air" in cell or "Condition" in cell or "AC" in cell):
                isAC += 1
        return False
    
    @staticmethod
    def extractActiveDates(serviceCol):
        pass

    def doRegisterServices(self, sheet, direction, numCols):
        serviceCols = sheet.columns
        for col in serviceCols[2:numCols]:
            idx = serviceCols.get_loc(col)
            clean = self.cleanCol(sheet, idx)
            # # print(clean)
            if (clean.empty):
                continue
            # skip repeat STATION columns
            if (not clean.empty and clean.iloc[0].strip().upper() == "STATIONS"):
                # print("repeat stations")
                continue

            # check for an ADAD column
            vals = clean.dropna().astype(str).str.strip().str.upper().tolist()
            isADAD = any(a == "A" and b == "D" for a, b in zip(vals, vals[1:]))
            if(isADAD):
                # print("adad column, skip") # ideally eliminate from the sheet before
                continue
            
            # if we are here, the column is a service column
            # extract service ID and 
            service = Service(ServiceType.REGULAR)
            service.direction = direction
            service.rawServiceCol = clean

            sIds, rakeSize, zone, linkName = TimeTableParser.extractServiceHeader(clean)
            # assign service id(s)
            if (not len(sIds)): 
                service.type = ServiceType.STABLING # no SID
            if (len(sIds) > 1):
                service.type = ServiceType.MULTI_SERVICE # multiple SIDs

            service.serviceId = sIds
            service.rakeSizeReq = rakeSize
            service.zone = zone
            # service.rakeLinkName = linkName # initially None
            # service.line = self.determineLineType(clean, sheet)

            # needs AC?
            # Most AC services have specific dates.
            service.needsACRake = TimeTableParser.extractACRequirement(clean)
            # # print(f"{service.serviceId}: {service.needsACRake}")

            # retrieve the station path 
            service.initStation = self.extractInitStation(clean, sheet)
            # print(f"Init station for {service.serviceId}: {service.initStation.name}")

            service.finalStation = self.extractFinalStation(clean, sheet)
            # if (service.finalStation):
            #     print(f"Final Station for {service.serviceId}: {service.finalStation.name}")
            # else:
            #     print(f"Could not find final station for {service.serviceId}")

            service.linkedTo = self.extractLinkedToNext(clean, direction)
            # print(f"Service {service.serviceId} linked to service: {service.linkedTo}")
            # print(service)

            if direction == Direction.UP:
                self.wtt.upServices.append(service)
            elif direction == Direction.DOWN:
                self.wtt.downServices.append(service)
            else:
                print("No other possibility")
        
    # Regular service columns, we parse:
    # - Stations with arrival and departures.
    def registerServices(self):
        '''Enumerate every possible service, extract arrival-departure timings. Populate
        the Station events. For now, store up and down services seperately
        '''
        UP_TT_COLUMNS = 949 # with uniform row indexing, last = 91024
        upSheet = self.upSheet
        self.doRegisterServices(upSheet, Direction.UP, UP_TT_COLUMNS)
        

        # print("Now register down services")
        downSheet = self.downSheet
        DOWN_TT_COLUMNS = 982 # with uniform row indexing, last = 91055
        self.doRegisterServices(downSheet, Direction.DOWN, DOWN_TT_COLUMNS)
        # print("Down services registered")

        # # print(len(TimeTableParser.rakeLinkNames))
        # # print("AL" in TimeTableParser.rakeLinkNames)

        
if __name__ == "__main__":
    wttPath = "/home/armaan/Fun-CS/IITB-RAILWAYS-2025/railways-simulator-IITB/SWTT-78_ADDITIONAL_AC_SERVICES_27_NOV_2024-1.xlsx"
    wttSummaryPath = "/home/armaan/Fun-CS/IITB-RAILWAYS-2025/railways-simulator-IITB/LINK_SWTT_78_UPDATED_05.11.2024-4.xlsx"
    parsed = TimeTableParser(wttPath, wttSummaryPath)

    parsed.wtt.generateRakeCycles()

    # parsed.verify()
    
    parsed.wtt.printStatistics()


# Summary Sheet
# - Contains the serviceID of every rake cycle in the suburban network.
# - Includes info on starting point of the rake (carshed, yard, etc.)
# - Includes info on whether the train is FAST/SLOW (slow: no station skipped. Fast: Some stations skipped)



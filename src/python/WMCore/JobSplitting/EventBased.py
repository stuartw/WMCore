#!/usr/bin/env python
"""
_EventBased_

Event based splitting algorithm that will chop a fileset into
a set of jobs based on event counts
"""


from WMCore.JobSplitting.JobFactory import JobFactory
from WMCore.WMBS.File               import File
from WMCore.DataStructs.Run import Run
from math import ceil

class EventBased(JobFactory):
    """
    Split jobs by number of events
    """
    def algorithm(self, *args, **kwargs):
        """
        _algorithm_

        An event base splitting algorithm.  All available files are split into a
        set number of events per job.
        """
        eventsPerJob = int(kwargs.get("events_per_job", 100))
        eventsPerLumi = int(kwargs.get("events_per_lumi", eventsPerJob))
        getParents   = kwargs.get("include_parents", False)


        totalJobs    = 0

        locationDict = self.sortByLocation()
        for location in locationDict:
            self.newGroup()
            fileList = locationDict[location]
            getRunLumiInformation = False
            for f in fileList:
                if f['lfn'].startswith("MCFakeFile"):
                    #We have one MCFakeFile, then it needs run information
                    getRunLumiInformation = True
                    break
            if getRunLumiInformation:
                if self.package == 'WMCore.WMBS':
                    loadRunLumi = self.daoFactory(
                                        classname = "Files.GetBulkRunLumi")
                    fileLumis = loadRunLumi.execute(files = fileList)
                    for f in fileList:
                        lumiDict = fileLumis.get(f['id'], {})
                        for run in lumiDict.keys():
                            f.addRun(run = Run(run, *lumiDict[run]))
            for f in fileList:
                currentEvent = f['first_event']
                eventsInFile = f['events']
                runs = list(f['runs'])
                #We got the runs, clean the file.
                f['runs'] = set()

                if getParents:
                    parentLFNs = self.findParent(lfn = f['lfn'])
                    for lfn in parentLFNs:
                        parent = File(lfn = lfn)
                        f['parents'].add(parent)

                if not f['lfn'].startswith("MCFakeFile"):
                    #Then we know for sure it is not a MCFakeFile, so process
                    #it as usual
                    if eventsInFile >= eventsPerJob:
                        while currentEvent < eventsInFile:
                            self.newJob(name = self.getJobName(length=totalJobs))
                            self.currentJob.addFile(f)
                            if eventsPerJob + currentEvent < eventsInFile:
                                self.currentJob["mask"].setMaxAndSkipEvents(eventsPerJob, currentEvent)
                            else:
                                self.currentJob["mask"].setMaxAndSkipEvents(eventsInFile - currentEvent,
                                                                            currentEvent)
                            currentEvent += eventsPerJob
                            totalJobs    += 1
                    else:
                        self.newJob(name = self.getJobName(length=totalJobs))
                        self.currentJob.addFile(f)
                        if f["events"]:
                            self.currentJob["mask"].setMaxAndSkipEvents(f["events"], 0)
                        totalJobs += 1
                else:
                    #This assumes there's only one run which is the case for MC
                    lumis = runs[0].lumis
                    (firstLumi, lastLumi) = (min(lumis), max(lumis))
                    currentLumi = firstLumi
                    totalEvents = 0
                    if eventsInFile >= eventsPerJob:
                        while totalEvents < eventsInFile:
                            self.newJob(name = self.getJobName(length=totalJobs))
                            self.currentJob.addFile(f)
                            lumisPerJob = int(ceil(float(eventsPerJob)
                                                / eventsPerLumi))
                            #Limit the number of events to a unsigned 32bit int
                            eventsRemaining = eventsInFile - totalEvents
                            if (currentEvent + eventsPerJob - 1) > (2**32 - 1) and (currentEvent + eventsRemaining - 1) > (2**32 - 1):
                                currentEvent = 1
                            if eventsRemaining > eventsPerJob:
                                self.currentJob["mask"].setMaxAndSkipEvents(eventsPerJob,
                                                                            currentEvent)
                                self.currentJob["mask"].setMaxAndSkipLumis(lumisPerJob,
                                                                           currentLumi)
                            else:
                                lumisPerJob = int(ceil(float(eventsRemaining)/eventsPerLumi))
                                self.currentJob["mask"].setMaxAndSkipEvents(eventsRemaining,
                                                                            currentEvent)
                                self.currentJob["mask"].setMaxAndSkipLumis(lumisPerJob,
                                                                           currentLumi)
                            currentLumi  += lumisPerJob
                            currentEvent += eventsPerJob
                            totalEvents  += eventsPerJob
                            totalJobs    += 1
                    else:
                        self.newJob(name = self.getJobName(length=totalJobs))
                        self.currentJob.addFile(f)
                        #For MC we use firstEvent instead of skipEvents so set it to 1
                        #We must check for events going over 2**32 - 1 here too
                        if (eventsInFile + currentEvent - 1) > (2**32 - 1):
                            currentEvent = 1
                        self.currentJob["mask"].setMaxAndSkipEvents(eventsInFile,
                                                                    currentEvent)
                        self.currentJob["mask"].setMaxAndSkipLumis(lastLumi -
                                                        currentLumi + 1, currentLumi)
                        totalJobs += 1

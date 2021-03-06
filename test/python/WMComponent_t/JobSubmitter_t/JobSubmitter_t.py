#!/bin/env python

"""
_JobSubmitter_t_

JobSubmitter unittest
Submit jobs to condor in various failure modes
for the agent and see what they do
"""

import unittest
import threading
import os
import os.path
import time
import shutil
import pickle
import cProfile
import pstats
import copy
import getpass
import re
import cPickle

from subprocess import Popen, PIPE


import WMCore.WMBase
import WMCore.WMInit
#from WMQuality.TestInit import TestInit
from WMQuality.TestInitCouchApp import TestInitCouchApp as TestInit
from WMCore.DAOFactory          import DAOFactory
from WMCore.WMInit              import getWMBASE

from WMCore.WMBS.File         import File
from WMCore.WMBS.Fileset      import Fileset
from WMCore.WMBS.Workflow     import Workflow
from WMCore.WMBS.Subscription import Subscription
from WMCore.WMBS.JobGroup     import JobGroup
from WMCore.WMBS.Job          import Job



from WMComponent.JobSubmitter.JobSubmitter       import JobSubmitter
from WMComponent.JobSubmitter.JobSubmitterPoller import JobSubmitterPoller

from WMCore.JobStateMachine.ChangeState import ChangeState

from WMCore.Services.UUID import makeUUID

from WMCore.Agent.Configuration             import loadConfigurationFile, Configuration
from WMCore.ResourceControl.ResourceControl import ResourceControl
from WMCore.DataStructs.JobPackage          import JobPackage
from WMCore.Agent.HeartbeatAPI              import HeartbeatAPI


#Workload stuff
from WMCore.WMSpec.WMWorkload import newWorkload
from WMCore.WMSpec.WMStep import makeWMStep
from WMCore.WMSpec.Steps.StepFactory import getStepTypeHelper
from WMCore.WMSpec.Makers.TaskMaker import TaskMaker
from WMCore.WMSpec.StdSpecs.ReReco  import rerecoWorkload, getTestArguments
from WMCore_t.WMSpec_t.TestSpec import testWorkload

from nose.plugins.attrib import attr

def parseJDL(jdlLocation):
    """
    _parseJDL_

    Parse a JDL into some sort of meaningful dictionary
    """


    f = open(jdlLocation, 'r')
    lines = f.readlines()
    f.close()


    listOfJobs = []
    headerDict = {}
    jobLines   = []

    index = 0

    for line in lines:
        # Go through the lines until you hit Queue
        index += 1
        splits = line.split(' = ')
        key = splits[0]
        value = ' = '.join(splits[1:])
        value = value.rstrip('\n')
        headerDict[key] = value
        if key == "Queue 1\n":
            # Yes, this is clumsy
            jobLines = lines[index:]
            break

    tmpDict = {}
    index   = 2
    for jobLine in jobLines:
        splits = jobLine.split(' = ')
        key = splits[0]
        value = ' = '.join(splits[1:])
        value = value.rstrip('\n')
        if key == "Queue 1\n":
            # Then we've hit the next block
            tmpDict["index"] = index
            listOfJobs.append(tmpDict)
            tmpDict = {}
            index += 1
        else:
            tmpDict[key] = value

    if tmpDict != {}:
        listOfJobs.append(tmpDict)


    return listOfJobs, headerDict



def getCondorRunningJobs(user):
    """
    _getCondorRunningJobs_

    Return the number of jobs currently running for a user
    """


    command = ['condor_q', user]
    pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
    stdout, error = pipe.communicate()

    output = stdout.split('\n')[-2]

    nJobs = int(output.split(';')[0].split()[0])

    return nJobs


        

class JobSubmitterTest(unittest.TestCase):
    """
    Test class for the JobSubmitter

    """

    sites = ['T2_US_Florida', 'T2_US_UCSD', 'T2_TW_Taiwan', 'T1_CH_CERN']

    def setUp(self):
        """
        Standard setup: Now with 100% more couch
        """

        self.testInit = TestInit(__file__)
        self.testInit.setLogging()
        self.testInit.setDatabaseConnection(destroyAllDatabase = True)
        self.testInit.setSchema(customModules = ["WMCore.WMBS", "WMCore.BossAir", "WMCore.ResourceControl", "WMCore.Agent.Database"],
                                useDefault = False)
        self.testInit.setupCouch("jobsubmitter_t/jobs", "JobDump")
        self.testInit.setupCouch("jobsubmitter_t/fwjrs", "FWJRDump")
        
        myThread = threading.currentThread()
        self.daoFactory = DAOFactory(package = "WMCore.WMBS",
                                     logger = myThread.logger,
                                     dbinterface = myThread.dbi)
        
        locationAction = self.daoFactory(classname = "Locations.New")
        locationSlots  = self.daoFactory(classname = "Locations.SetJobSlots")

        # We actually need the user name
        self.user = getpass.getuser()

        self.ceName = '127.0.0.1'

        #Create sites in resourceControl
        resourceControl = ResourceControl()
        for site in self.sites:
            resourceControl.insertSite(siteName = site, seName = 'se.%s' % (site),
                                       ceName = site, plugin = "CondorPlugin", pendingSlots = 10000,
                                       runningSlots = 20000, cmsName = site)
            resourceControl.insertThreshold(siteName = site, taskType = 'Processing', \
                                            maxSlots = 10000)


        self.testDir = self.testInit.generateWorkDir()

        # Set heartbeat
        self.componentName = 'JobSubmitter'
        self.heartbeatAPI  = HeartbeatAPI(self.componentName)
        self.heartbeatAPI.registerComponent()
            
        return

    def tearDown(self):
        """
        Standard tearDown

        """
        self.testInit.clearDatabase(modules = ["WMCore.WMBS",
                                               'WMCore.ResourceControl', 'WMCore.BossAir',
                                               'WMCore.Agent.Database'])
        self.testInit.delWorkDir()

        self.testInit.tearDownCouch()

        return



    def createJobGroups(self, nSubs, nJobs, task, workloadSpec, site = None,
                        bl = [], wl = [], type = 'Processing'):
        """
        Creates a series of jobGroups for submissions

        """

        jobGroupList = []

        testWorkflow = Workflow(spec = workloadSpec, owner = "mnorman",
                                name = makeUUID(), task="basicWorkload/Production")
        testWorkflow.create()

        # Create subscriptions
        for i in range(nSubs):

            name = makeUUID()

            # Create Fileset, Subscription, jobGroup
            testFileset = Fileset(name = name)
            testFileset.create()
            testSubscription = Subscription(fileset = testFileset,
                                            workflow = testWorkflow,
                                            type = type,
                                            split_algo = "FileBased")
            testSubscription.create()

            testJobGroup = JobGroup(subscription = testSubscription)
            testJobGroup.create()


            # Create jobs
            self.makeNJobs(name = name, task = task,
                           nJobs = nJobs,
                           jobGroup = testJobGroup,
                           fileset = testFileset,
                           sub = testSubscription.exists(),
                           site = site, bl = bl, wl = wl)
                                         


            testFileset.commit()
            testJobGroup.commit()
            jobGroupList.append(testJobGroup)

        return jobGroupList
            


    def makeNJobs(self, name, task, nJobs, jobGroup, fileset, sub, site = None, bl = [], wl = []):
        """
        _makeNJobs_

        Make and return a WMBS Job and File
        This handles all those damn add-ons

        """
        # Set the CacheDir
        cacheDir = os.path.join(self.testDir, 'CacheDir')

        for n in range(nJobs):
            # First make a file
            #site = self.sites[0]
            testFile = File(lfn = "/singleLfn/%s/%s" %(name, n),
                            size = 1024, events = 10)
            if site:
                testFile.setLocation(site)
            else:
                for tmpSite in self.sites:
                    testFile.setLocation('se.%s' % (tmpSite))
            testFile.create()
            fileset.addFile(testFile)


        fileset.commit()

        index = 0
        for f in fileset.files:
            index += 1
            testJob = Job(name = '%s-%i' %(name, index))
            testJob.addFile(f)
            testJob["location"]  = f.getLocations()[0]
            testJob['task']    = task.getPathName()
            testJob['sandbox'] = task.data.input.sandbox
            testJob['spec']    = os.path.join(self.testDir, 'basicWorkload.pcl')
            testJob['mask']['FirstEvent'] = 101
            testJob["siteBlacklist"] = bl
            testJob["siteWhitelist"] = wl
            testJob['priority']      = 101
            jobCache = os.path.join(cacheDir, 'Sub_%i' % (sub), 'Job_%i' % (index))
            os.makedirs(jobCache)
            testJob.create(jobGroup)
            testJob['cache_dir'] = jobCache
            testJob.save()
            jobGroup.add(testJob)
            output = open(os.path.join(jobCache, 'job.pkl'),'w')
            pickle.dump(testJob, output)
            output.close()

        return testJob, testFile
        

    def getConfig(self, configPath = os.path.join(WMCore.WMInit.getWMBASE(), 'src/python/WMComponent/JobSubmitter/DefaultConfig.py')):
        """
        _getConfig_

        Gets a basic config from default location
        """

        myThread = threading.currentThread()

        config = Configuration()

        config.component_("Agent")
        config.Agent.WMSpecDirectory = self.testDir
        config.Agent.agentName       = 'testAgent'
        config.Agent.componentName   = self.componentName
        config.Agent.useHeartbeat    = False


        #First the general stuff
        config.section_("General")
        config.General.workDir = os.getenv("TESTDIR", self.testDir)

        #Now the CoreDatabase information
        #This should be the dialect, dburl, etc

        config.section_("CoreDatabase")
        config.CoreDatabase.connectUrl = os.getenv("DATABASE")
        config.CoreDatabase.socket     = os.getenv("DBSOCK")

        config.section_("BossAir")
        config.BossAir.pluginNames = ['TestPlugin', 'CondorPlugin']
        config.BossAir.pluginDir   = 'WMCore.BossAir.Plugins'

        config.component_("JobSubmitter")
        config.JobSubmitter.logLevel      = 'INFO'
        config.JobSubmitter.maxThreads    = 1
        config.JobSubmitter.pollInterval  = 10
        config.JobSubmitter.pluginName    = 'CondorGlobusPlugin'
        config.JobSubmitter.pluginDir     = 'JobSubmitter.Plugins'
        config.JobSubmitter.submitNode    = os.getenv("HOSTNAME", 'badtest.fnal.gov')
        config.JobSubmitter.submitScript  = os.path.join(WMCore.WMBase.getTestBase(),
                                                         'WMComponent_t/JobSubmitter_t',
                                                         'submit.sh')
        config.JobSubmitter.componentDir  = os.path.join(self.testDir, 'Components')
        config.JobSubmitter.workerThreads = 2
        config.JobSubmitter.jobsPerWorker = 200
        config.JobSubmitter.inputFile     = os.path.join(WMCore.WMBase.getTestBase(),
                                                         'WMComponent_t/JobSubmitter_t',
                                                         'FrameworkJobReport-4540.xml')
        config.JobSubmitter.deleteJDLFiles = False


        #JobStateMachine
        config.component_('JobStateMachine')
        config.JobStateMachine.couchurl        = os.getenv('COUCHURL')
        config.JobStateMachine.couchDBName     = "jobsubmitter_t"


        # Needed, because this is a test
        os.makedirs(config.JobSubmitter.componentDir)


        return config
    
    def createTestWorkload(self, workloadName = 'Test', emulator = True):
        """
        _createTestWorkload_

        Creates a test workload for us to run on, hold the basic necessities.
        """

        workload = testWorkload("Tier1ReReco")
        rereco = workload.getTask("ReReco")

        
        taskMaker = TaskMaker(workload, os.path.join(self.testDir, 'workloadTest'))
        taskMaker.skipSubscription = True
        taskMaker.processWorkload()

        return workload


    def checkJDL(self, config, cacheDir, submitFile, site = None, indexFlag = False, noIndex = False):
        """
        _checkJDL_

        Check the basic JDL setup
        """

        jobs, head = parseJDL(jdlLocation = os.path.join(config.JobSubmitter.submitDir,
                                                         submitFile))

        batch = 1

        # Check each job entry in the JDL
        for job in jobs:
            # Check each key
            index = int(job.get('+WMAgent_JobID', 0))
            self.assertTrue(index != 0)

            argValue = index -1
            if indexFlag:
                batch    = index - 1
            
            inputFileString = '%s, %s, %s' % (os.path.join(self.testDir, 'workloadTest/TestWorkload',
                                                           'TestWorkload-Sandbox.tar.bz2'),
                                              os.path.join(self.testDir, 'workloadTest/TestWorkload',
                                                           'PackageCollection_0/batch_%i-0/JobPackage.pkl' % (batch)),
                                              os.path.join(WMCore.WMInit.getWMBASE(), 'src/python/WMCore',
                                                           'WMRuntime/Unpacker.py'))
            if not noIndex:
                self.assertEqual(job.get('transfer_input_files', None),
                                 inputFileString)
            # Arguments use a list starting from 0
            self.assertEqual(job.get('arguments', None),
                             'TestWorkload-Sandbox.tar.bz2 %i' % (index))

            if site:
                self.assertEqual(job.get('+DESIRED_Sites', None), '\"%s\"' % site)

            # Check the priority
            self.assertEqual(job.get('priority', None), '101')

        # Now handle the head
        self.assertEqual(head.get('should_transfer_files', None), 'YES')
        self.assertEqual(head.get('Log', None), 'condor.$(Cluster).$(Process).log')
        self.assertEqual(head.get('Error', None), 'condor.$(Cluster).$(Process).err')
        self.assertEqual(head.get('Output', None), 'condor.$(Cluster).$(Process).out')
        self.assertEqual(head.get('when_to_transfer_output', None), 'ON_EXIT')
        self.assertEqual(head.get('Executable', None), config.JobSubmitter.submitScript)

        return

            


    @attr('integration')
    def testA_BasicTest(self):
        """
        Use the CondorGlobusPlugin to create a very simple test
        Check to see that all the jobs were submitted
        Parse and test the JDL files
        See what condor says
        """
        workloadName = "basicWorkload"

        myThread = threading.currentThread()

        workload = self.createTestWorkload()

        config   = self.getConfig()

        changeState = ChangeState(config)

        nSubs = 1
        nJobs = 10
        cacheDir = os.path.join(self.testDir, 'CacheDir')

        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            site = 'se.T2_US_UCSD')
        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')


        # Do pre-submit check
        getJobsAction = self.daoFactory(classname = "Jobs.GetAllJobs")
        result = getJobsAction.execute(state = 'Created', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs)

        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))
        

        jobSubmitter = JobSubmitterPoller(config = config)
        jobSubmitter.algorithm()


        # Check that jobs are in the right state
        result = getJobsAction.execute(state = 'Created', jobType = "Processing")
        self.assertEqual(len(result), 0)
        result = getJobsAction.execute(state = 'Executing', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs)


        # Check assigned locations
        getLocationAction = self.daoFactory(classname = "Jobs.GetLocation")
        for id in result:
            loc = getLocationAction.execute(jobid = id)
            self.assertEqual(loc, [['T2_US_UCSD']])

        
        # Check on the JDL
        submitFile = None
        for file in os.listdir(config.JobSubmitter.submitDir):
            if re.search('submit', file):
                submitFile = file
        self.assertTrue(submitFile != None)
        self.checkJDL(config = config, cacheDir = cacheDir,
                      submitFile = submitFile, site = 'T2_US_UCSD')

        

        #if os.path.exists('CacheDir'):
        #    shutil.rmtree('CacheDir')
        #shutil.copytree(self.testDir, 'CacheDir')


        # Check to make sure we have running jobs
        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, nJobs * nSubs)

        # This should do nothing
        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            site = 'se.T2_US_UCSD')
        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')
        jobSubmitter.algorithm()

        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()

        del jobSubmitter

        
        return


    @attr('performance')
    def testB_TimeLongSubmission(self):
        """
        _TimeLongSubmission_

        Submit a lot of jobs and test how long it takes for
        them to actually be submitted
        """


        return


        workloadName = "basicWorkload"
        myThread     = threading.currentThread()
        workload     = self.createTestWorkload()
        config       = self.getConfig()
        changeState  = ChangeState(config)

        nSubs = 5
        nJobs = 300
        cacheDir = os.path.join(self.testDir, 'CacheDir')

        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName))

        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')

        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))


        jobSubmitter = JobSubmitterPoller(config = config)

        # Actually run it
        startTime = time.time()
        cProfile.runctx("jobSubmitter.algorithm()", globals(), locals(), filename = "testStats.stat")
        #jobSubmitter.algorithm()
        stopTime  = time.time()

        if os.path.isdir('CacheDir'):
            shutil.rmtree('CacheDir')
        shutil.copytree('%s' %self.testDir, os.path.join(os.getcwd(), 'CacheDir'))


        # Check to make sure we have running jobs
        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, nJobs * nSubs)


        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()


        print "Job took %f seconds to complete" %(stopTime - startTime)


        p = pstats.Stats('testStats.stat')
        p.sort_stats('cumulative')
        p.print_stats()

        return

        
    def testD_CreamCETest(self):
        """
        _CreamCETest_

        This is for submitting to Cream CEs.  Don't use it.
        """

        return

        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))


        workloadName = "basicWorkload"

        myThread = threading.currentThread()

        workload = self.createTestWorkload()

        config   = self.getConfig()
        config.JobSubmitter.pluginName    = 'CreamPlugin'

        changeState = ChangeState(config)

        nSubs = 1
        nJobs = 10
        cacheDir = os.path.join(self.testDir, 'CacheDir')

        # Add a new site
        siteName = "creamSite"
        ceName = "https://cream-1-fzk.gridka.de:8443/ce-cream/services/CREAM2  pbs cmsXS"
        #ceName = "127.0.0.1"
        locationAction = self.daoFactory(classname = "Locations.New")
        pendingSlots  = self.daoFactory(classname = "Locations.SetPendingSlots")
        locationAction.execute(siteName = siteName, seName = siteName, ceName = ceName)
        pendingSlots.execute(siteName = siteName, pendingSlots = 1000)

        resourceControl = ResourceControl()
        resourceControl.insertSite(siteName = siteName, seName = siteName, ceName = ceName)
        resourceControl.insertThreshold(siteName = siteName, taskType = 'Processing', \
                                        maxSlots = 10000)
        

        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            site = siteName)
        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')



        jobSubmitter = JobSubmitterPoller(config = config)
        jobSubmitter.algorithm()


        # Check that jobs are in the right state
        getJobsAction = self.daoFactory(classname = "Jobs.GetAllJobs")
        result = getJobsAction.execute(state = 'Created', jobType = "Processing")
        self.assertEqual(len(result), 0)
        result = getJobsAction.execute(state = 'Executing', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs)


        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()

        if os.path.exists('CacheDir'):
            shutil.rmtree('CacheDir')
        shutil.copytree(self.testDir, 'CacheDir')

        return

    @attr('integration')
    def testE_WhiteListBlackList(self):
        """
        _WhiteListBlackList_

        Test the whitelist/blacklist implementation
        Trust the jobCreator to get this in the job right
        """
        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))

        workloadName = "basicWorkload"
        myThread     = threading.currentThread()
        workload     = self.createTestWorkload()
        config       = self.getConfig()
        changeState  = ChangeState(config)

        nSubs = 2
        nJobs = 10
        cacheDir = os.path.join(self.testDir, 'CacheDir')

        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            bl = ['T2_US_Florida', 'T2_TW_Taiwan', 'T1_CH_CERN'])

        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')

        


        jobSubmitter = JobSubmitterPoller(config = config)

        # Actually run it
        jobSubmitter.algorithm()

        if os.path.isdir('CacheDir'):
            shutil.rmtree('CacheDir')
        shutil.copytree('%s' %self.testDir, os.path.join(os.getcwd(), 'CacheDir'))


        # Check to make sure we have running jobs
        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, nJobs * nSubs)

        getJobsAction = self.daoFactory(classname = "Jobs.GetAllJobs")
        result = getJobsAction.execute(state = 'Executing', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs)

        # All jobs should be at UCSD
        submitFile = None
        for file in os.listdir(config.JobSubmitter.submitDir):
            if re.search('submit', file):
                submitFile = file
        self.assertTrue(submitFile != None)
        #submitFile = os.listdir(config.JobSubmitter.submitDir)[0]
        self.checkJDL(config = config, cacheDir = cacheDir,
                      submitFile = submitFile, site = 'T2_US_UCSD')


        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()






        # Run again and test the whiteList
        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            wl = ['T2_US_UCSD'])

        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')

        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))


        jobSubmitter = JobSubmitterPoller(config = config)

        # Actually run it
        jobSubmitter.algorithm()

        if os.path.isdir('CacheDir'):
            shutil.rmtree('CacheDir')
        shutil.copytree('%s' %self.testDir, os.path.join(os.getcwd(), 'CacheDir'))


        # Check to make sure we have running jobs
        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, nJobs * nSubs)

        # You'll have jobs from the previous run still in the database
        result = getJobsAction.execute(state = 'Executing', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs * 2)

        # All jobs should be at UCSD
        submitFile = None
        for file in os.listdir(config.JobSubmitter.submitDir):
            if re.search('submit', file):
                submitFile = file
        self.assertTrue(submitFile != None)
        self.checkJDL(config = config, cacheDir = cacheDir,
                      submitFile = submitFile, site = 'T2_US_UCSD', noIndex = True)


        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()






        # Run again with an invalid whitelist
        # NOTE: After this point, the original two sets of jobs will be executing
        # The rest of the jobs should move to submitFailed
        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            wl = ['T2_US_Namibia'])

        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')

        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))


        jobSubmitter = JobSubmitterPoller(config = config)

        # Actually run it
        jobSubmitter.algorithm()


        # Check to make sure we have running jobs
        #nRunning = getCondorRunningJobs(self.user)
        #self.assertEqual(nRunning, 0)

        # Jobs should be gone
        getJobsAction = self.daoFactory(classname = "Jobs.GetAllJobs")
        result = getJobsAction.execute(state = 'Executing', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs * 2)
        result = getJobsAction.execute(state = 'SubmitFailed', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs)



        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()






        # Run again with all sites blacklisted
        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            bl = self.sites)

        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')

        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))


        jobSubmitter = JobSubmitterPoller(config = config)

        # Actually run it
        jobSubmitter.algorithm()


        # Check to make sure we have running jobs
        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0)

        # Jobs should be gone
        getJobsAction = self.daoFactory(classname = "Jobs.GetAllJobs")
        result = getJobsAction.execute(state = 'Executing', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs * 2)
        result = getJobsAction.execute(state = 'SubmitFailed', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs * 2)



        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()

        del jobSubmitter
        return


    @attr('integration')
    def testF_OverloadTest(self):
        """
        _OverloadTest_
        
        Test and see what happens if you put in more jobs
        Then the sites can handle
        """

        resourceControl = ResourceControl()
        for site in self.sites:
            resourceControl.insertThreshold(siteName = site, taskType = 'Silly', \
                                            maxSlots = 1)



        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))

        workloadName = "basicWorkload"
        myThread     = threading.currentThread()
        workload     = self.createTestWorkload()
        config       = self.getConfig()
        changeState  = ChangeState(config)

        nSubs = 2
        nJobs = 10
        cacheDir = os.path.join(self.testDir, 'CacheDir')

        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            type = 'Silly')

        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')

        


        jobSubmitter = JobSubmitterPoller(config = config)

        # Actually run it
        jobSubmitter.algorithm()

        # Should be one job for each site
        nSites = len(self.sites)
        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, nSites)


        getJobsAction = self.daoFactory(classname = "Jobs.GetAllJobs")
        result = getJobsAction.execute(state = 'Executing', jobType = "Silly")
        self.assertEqual(len(result), nSites)
        result = getJobsAction.execute(state = 'Created', jobType = "Silly")
        self.assertEqual(len(result), nJobs*nSubs - nSites)


        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()

        del jobSubmitter

        return


    @attr('integration')
    def testG_IndexErrorTest(self):
        """
        _IndexErrorTest_

        Check to see you get proper indexes for the jobPackages
        if you have more jobs then you normally run at once.
        """
        workloadName = "basicWorkload"

        myThread = threading.currentThread()

        workload = self.createTestWorkload()

        config   = self.getConfig()
        config.JobSubmitter.jobsPerWorker  = 1
        config.JobSubmitter.collectionSize = 1

        changeState = ChangeState(config)

        nSubs = 1
        nJobs = 10
        cacheDir = os.path.join(self.testDir, 'CacheDir')

        jobGroupList = self.createJobGroups(nSubs = nSubs, nJobs = nJobs,
                                            task = workload.getTask("ReReco"),
                                            workloadSpec = os.path.join(self.testDir,
                                                                        'workloadTest',
                                                                        workloadName),
                                            site = 'se.T2_US_UCSD')
        for group in jobGroupList:
            changeState.propagate(group.jobs, 'created', 'new')


        # Do pre-submit check
        getJobsAction = self.daoFactory(classname = "Jobs.GetAllJobs")
        result = getJobsAction.execute(state = 'Created', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs)

        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, 0, "User currently has %i running jobs.  Test will not continue" % (nRunning))
        

        jobSubmitter = JobSubmitterPoller(config = config)
        jobSubmitter.algorithm()


        if os.path.exists('CacheDir'):
            shutil.rmtree('CacheDir')
        shutil.copytree(self.testDir, 'CacheDir')


        # Check that jobs are in the right state
        result = getJobsAction.execute(state = 'Created', jobType = "Processing")
        self.assertEqual(len(result), 0)
        result = getJobsAction.execute(state = 'Executing', jobType = "Processing")
        self.assertEqual(len(result), nSubs * nJobs)

        
        # Check on the JDL
        submitFile = None
        for file in os.listdir(config.JobSubmitter.submitDir):
            if re.search('submit', file):
                submitFile = file
        self.assertTrue(submitFile != None)
        self.checkJDL(config = config, cacheDir = cacheDir,
                      submitFile = submitFile, site = 'T2_US_UCSD', indexFlag = True)



        # Check to make sure we have running jobs
        nRunning = getCondorRunningJobs(self.user)
        self.assertEqual(nRunning, nJobs * nSubs)

        


        # Now clean-up
        command = ['condor_rm', self.user]
        pipe = Popen(command, stdout = PIPE, stderr = PIPE, shell = False)
        pipe.communicate()

        del jobSubmitter
        return


if __name__ == "__main__":
    unittest.main() 

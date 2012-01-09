"""
Perform cleanup actions
"""
__all__ = []



import threading
import logging
import time
from WMCore.WorkerThreads.BaseWorkerThread import BaseWorkerThread
from WMCore.Services.WorkQueue.WorkQueue import WorkQueue as WorkQueueService
from WMCore.Services.WMStats.WMStatsWriter import WMStatsWriter
from WMComponent.AnalyticsDataCollector.DataCollectAPI import LocalCouchDBData, \
     WMAgentDBData, combineAnalyticsData, convertToStatusSiteFormat, getCouchACDCHtmlBase


class AnalyticsPoller(BaseWorkerThread):
    """
    Cleans expired items, updates element status.
    """
    def __init__(self, config):
        """
        Initialize config
        """
        BaseWorkerThread.__init__(self)
        # set the workqueue service for REST call
        self.config = config
        self.agentInfo = {}
        self.agentInfo['team'] = config.Agent.teamName
        self.agentInfo['agent'] = config.Agent.agentName
        self.agentInfo['agent_url'] = config.Agent.hostName
        # need to get campaign, user, owner info
        self.agentDocID = "agent+hostname"

    def setup(self, parameters):
        """
        Called at startup - introduce random delay
             to avoid workers all starting at once
        """
        
        #
        self.localQueue = WorkQueueService(self.config.AnalyticsDataCollector.localQueueURL)
        
        # set the connection for local couchDB call
        self.localCouchDB = LocalCouchDBData(self.config.AnalyticsDataCollector.localCouchURL)
        
        # interface to WMBS/BossAir db
        myThread = threading.currentThread()
        # set wmagent db data
        self.wmagentDB = WMAgentDBData(myThread.dbi, myThread.logger)
        # set the connection for local couchDB call
        self.localSummaryCouchDB = WMStatsWriter(self.config.AnalyticsDataCollector.localWMStatsURL )
        self.centralWMStats = WMStatsWriter(self.config.AnalyticsDataCollector.centralMStatsURL )
        
    def algorithm(self, parameters):
        """
        get information from wmbs, workqueue and local couch
        """
        try:
            #jobs per request info
            jobInfoFromCouch = self.localCouchDB.getJobSummaryByWorkflowAndSite()
            logging.debug("CouchData %s" % jobInfoFromCouch)
            batchJobInfo = self.wmagentDB.getBatchJobInfo()
            logging.debug("BatchJobData %s" % batchJobInfo)
            # get the data from local workqueue:
            # request name, input dataset, inWMBS, inQueue
            localQInfo = self.localQueue.getAnalyticsData()
            
            logging.debug("WorkQueueData %s" % localQInfo)
            
            # combine all the data from 3 sources
            tempCombinedData = combineAnalyticsData(jobInfoFromCouch, batchJobInfo)
            logging.debug("temp combine data %s" % tempCombinedData)
            combinedRequests = combineAnalyticsData(tempCombinedData, localQInfo)
            logging.debug("combined requests  %s" % combinedRequests)
            requestDocs = []
            uploadTime = int(time.time())
            for request, status in combinedRequests.items():
                doc = {}
                doc.update(self.agentInfo)
                doc['type'] = "agent_request"
                doc['workflow'] = request
                # this will set doc['status'], and doc['sites']
                tempData = convertToStatusSiteFormat(status)
                doc['status'] = tempData['status']
                doc['sites'] = tempData['sites']
                doc['timestamp'] = uploadTime
                requestDocs.append(doc)

            self.localSummaryCouchDB.uploadData(requestDocs)
            logging.info("Data upload success\n %s request" % len(requestDocs))
            
            # update directly to the central WMStats couchDB
            self.centralWMStats.updateRequestsInfo(requestDocs)
            
            #agent info (include job Slots for the sites)
            agentInfo = self.wmagentDB.getHeartBeatWarning()
            agentInfo.update(self.agentInfo)
            #TODO: sets the _id as agent url, need to be unique
            agentInfo['_id'] = agentInfo["agent_url"]
            acdcURL = '%s/%s' % (self.config.ACDC.couchurl, self.config.ACDC.database)
            agentInfo['acdc'] = getCouchACDCHtmlBase(acdcURL)
            
            agentInfo['timestamp'] = uploadTime
            agentInfo['type'] = "agent_info"
            self.localSummaryCouchDB.updateAgentInfo(agentInfo)

        except Exception, ex:
            logging.error(str(ex))
            raise

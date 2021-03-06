"""
Provide functions to collect data and upload data
"""

"""
JobInfoByID

Retrieve information about a job from couch and format it nicely.
"""


import logging
from WMCore.Lexicon import splitCouchServiceURL

REQUEST_NAME_PREFIX = "test-request-"
SITE_NAME_PREFIX = "T1_test-site-"
NUM_REQUESTS = 2
NUM_SITES = 3
NUM_JOBS_EACH = 1
JOB_SLOTS = 1000
COUCH_JOB_STATUS = ['queued_first', 'queued_retry', 'cooloff', 'submitted_first', 
                    'submitted_retry', 'success', 
                    'failure_exception', 'failure_submit', 
                    'failure_create', 'failure_cancel']
QUEUE_JOB_STATUS = ['inQueue', 'inWMBS']
BATCH_JOB_STATUS = ['submitted_pending', 'submitted_running']

class LocalCouchDBData():

    def __init__(self, couchURL):
        # set the connection for local couchDB call
        print "Using LocalCouchDBData Emulator"
        self.couchURL = couchURL
        self.couchURLBase, self.dbName = splitCouchServiceURL(couchURL)
        logging.info("connect couch %s:  %s" % (self.couchURLBase, self.dbName))
        
    def getJobSummaryByWorkflowAndSite(self):
        """
        gets the job status information by workflow
    
        example
        {"rows":[
            {"key":['request_name1", "queued_first", "siteA"],"value":100},
            {"key":['request_name1", "queued_first", "siteB"],"value":100},
            {"key":['request_name1", "running", "siteA"],"value":100},
            {"key":['request_name1", "success", "siteB"],"value":100}\
         ]}
         
         and convert to 
         {'request_name1': {'queue_first'; { 'siteA': 100}}
          'request_name1': {'queue_first'; { 'siteB': 100}}
         }
        """
        doc = {}
        for i in range(NUM_REQUESTS):
            request = doc['%s%s' % (REQUEST_NAME_PREFIX, i+1)] = {}
            for status in COUCH_JOB_STATUS:
                request[status] = {}
                for j in range(NUM_SITES):
                    request[status]['%s%s' % (SITE_NAME_PREFIX, j+1)] = NUM_JOBS_EACH

        return doc

class ReqMonDBData():

    def __init__(self, couchURL):
        # set the connection for local couchDB call
        self.couchURL, self.dbName = splitCouchServiceURL(couchURL)

    def uploadData(self, doc):
        """
        upload to given couchURL using cert and key authentication and authorization
        """
        return {'status':'ok'}

class WMAgentDBData():

    def __init__(self, dbi, logger):
        
        # interface to WMBS/BossAir db
        print "Using %s Emulator" % self.__class__
        
    def getHeartBeatWarning(self, agentURL, acdcLink):
        
        agentInfo = {}
        agentInfo['status'] = 'ok'
        agentInfo['url'] = agentURL
        agentInfo['acdc'] = acdcLink
        return agentInfo

    def getBatchJobInfo(self):
        """
        TODO: need to sync the job number (num of running job should match)
        """
        doc = {}
        for i in range(NUM_REQUESTS):
            request = doc['%s%s' % (REQUEST_NAME_PREFIX, i+1)] = {}
            for status in BATCH_JOB_STATUS:
                request[status] = {}
                for j in range(NUM_SITES):
                    request[status]['%s%s' % (SITE_NAME_PREFIX, j+1)] = NUM_JOBS_EACH

        return doc

    def getJobSlotInfo(self):
        
        results = []
        for i in range(NUM_SITES):
            doc = {}
            doc['cms_name'] = '%s%s' % (SITE_NAME_PREFIX, i+1)
            doc['job_slots'] = JOB_SLOTS
            results.append(doc)
        return results
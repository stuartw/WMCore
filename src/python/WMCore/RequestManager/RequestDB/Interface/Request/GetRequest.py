#!/usr/bin/env python
"""
_GetRequest_


API to get requests from the DB

"""
import logging
import WMCore.RequestManager.RequestDB.Connection as DBConnect
import WMCore.RequestManager.RequestDB.Interface.Request.ListRequests as ListRequests
import WMCore.RequestManager.RequestDB.Interface.Request.ChangeState as ChangeState
from WMCore.RequestManager.DataStructs.Request import Request
from cherrypy import HTTPError

def reverseLookups():
    """ returns reverse lookups for Types and Status """
    factory = DBConnect.getConnection()
    reqTypes = factory(classname = 'ReqTypes.Map').execute()
    reqStatus = factory(classname = 'ReqStatus.Map').execute()
    reverseTypes = {}
    [ reverseTypes.__setitem__(v, k) for k, v in reqTypes.iteritems() ]
    reverseStatus = {}
    [ reverseStatus.__setitem__(v, k) for k, v in reqStatus.iteritems() ]
    return reverseTypes, reverseStatus

def getRequest(requestId, reverseTypes=None, reverseStatus=None):
    """
    _getRequest_


    retrieve a request based on the request id,
    return a ReqMgr.DataStructs.Request instance containing
    the information

    """
    factory = DBConnect.getConnection()
    reqGet = factory(classname = "Request.Get")
    reqData = reqGet.execute(requestId)
    requestName = reqData['request_name']

    if not reverseTypes or not reverseStatus:
        reverseTypes, reverseStatus = reverseLookups()

    getGroup = factory(classname = "Group.GetGroupFromAssoc")
    groupData = getGroup.execute(reqData['requestor_group_id'])

    getUser = factory(classname = "Requestor.GetUserFromAssoc")
    userData = getUser.execute(reqData['requestor_group_id'])
    request = Request()
    request["ReqMgrRequestID"] = reqData['request_id']
    request["RequestName"] = requestName
    request["RequestType"] = reverseTypes[reqData['request_type']]
    request["RequestStatus"] = reverseStatus[reqData['request_status']]
    request["RequestPriority"] = reqData['request_priority']
    request["ReqMgrRequestBasePriority"] = reqData['request_priority']
    request["RequestWorkflow"] = reqData['workflow']
    request["RequestNumEvents"] = reqData['request_num_events']
    request["RequestSizeFiles"] = reqData['request_size_files']
    request["RequestEventSize"] = reqData['request_event_size']

    request["Group"] = groupData['group_name']
    request["ReqMgrGroupID"] = groupData['group_id']
    request["ReqMgrGroupBasePriority"] = \
                        groupData['group_base_priority']
    request["Requestor"] = userData['requestor_hn_name']
    request["ReqMgrRequestorID"] = userData['requestor_id']
    request["ReqMgrRequestorBasePriority"] = \
                                userData['requestor_base_priority']
    request["RequestPriority"] = \
      request['RequestPriority'] + groupData['group_base_priority']
    request["RequestPriority"] = \
      request['RequestPriority'] + userData['requestor_base_priority']

    updates = ChangeState.getProgress(requestName)
    request['percent_complete'], request['percent_success'] = percentages(updates)
    sqDeps = factory(classname = "Software.GetByAssoc")
    swVers = sqDeps.execute(requestId)
    if swVers == {}:
        request['SoftwareVersions'] = ['DEPRECATED']
    else:
        request['SoftwareVersions'] = swVers.values()
    
    getDatasetsIn = factory(classname = "Datasets.GetInput")
    getDatasetsOut = factory(classname = "Datasets.GetOutput")
    datasetsIn = getDatasetsIn.execute(requestId)
    datasetsOut = getDatasetsOut.execute(requestId)
    request['InputDatasetTypes'] = datasetsIn
    request['InputDatasets'] = datasetsIn.keys()
    request['OutputDatasets'] = datasetsOut
    return request

def requestID(requestName):
    """ Finds the ReqMgr database ID for a request """
    factory = DBConnect.getConnection()
    f =  factory(classname = "Request.FindByName")
    id = f.execute(requestName)
    if id == None:
        raise HTTPError(404, 'Given requestName not found')
    return id

def getRequestByName(requestName):
    return getRequest(requestID(requestName))

def percentages(updates):
    """ returns percent complete and percent success, from a list of updates """
    percent_complete = 0
    percent_success = 0
    for update in updates:
        if update.has_key('percent_complete'):
            percent_complete = update['percent_complete']
        if update.has_key('percent_success'):
            percent_success = update['percent_success']
    return percent_complete, percent_success

def getRequestDetails(requestName):
    """ Return a dict with the intimate details of the request """
    requestId = requestID(requestName)
    request = getRequest(requestId)
    request['Assignments'] = getAssignmentsByName(requestName)
    request['RequestMessages'] = ChangeState.getMessages(requestName)
    request['RequestUpdates'] = ChangeState.getProgress(requestName)
    return request

def getRequests():
    """ This only fills the details needed to make succint browser tables,
        so some fields, such as InputDatasets or SoftwareVersions,
        need to be filled through getRequestDetails """
    requests = ListRequests.listRequests()
    reverseTypes, reverseStatus = reverseLookups()
    result = []
    for request in requests:
        result.append(getRequest(request['RequestID'], reverseTypes, reverseStatus))
    return result

def getRequestByPrepID(prepID):
    factory = DBConnect.getConnection()
    getID = factory(classname = "Request.FindByPrepID")
    requestIDs = getID.execute(prepID)
    return requestIDs
    
def getRequestDetails(requestName):
    """ Return a dict with the intimate details of the request """
    request = getRequestByName(requestName)
    request['Assignments'] = getAssignmentsByName(requestName)
    # show the status and messages
    request['RequestMessages'] = ChangeState.getMessages(requestName)
    # updates
    request['RequestUpdates'] = ChangeState.getProgress(requestName)
    # it returns a datetime object, which I can't pass through
    request['percent_complete'] = 0
    request['percent_success'] = 0
    for update in request['RequestUpdates']:
        update['update_time'] = str(update['update_time'])
        if update.has_key('percent_complete'):
            request['percent_complete'] = update['percent_complete']
        if update.has_key('percent_success'):
            request['percent_success'] = update['percent_success']
    return request

def getAllRequestDetails():
    requests = ListRequests.listRequests()
    result = []
    for request in requests:
        requestName = request['RequestName']
        details = getRequestDetails(requestName)
        # take out excessive information
        del details['RequestUpdates']
        del details['RequestMessages']
        result.append(details)
    return result 


def getRequestAssignments(requestId):
    """
    _getRequestAssignments_

    Get the assignments to production teams for a request

    """
    factory = DBConnect.getConnection()
    getAssign = factory(classname = "Assignment.GetByRequest")
    result = getAssign.execute(requestId)
    return result

def getRequestsByCriteria(classname, criterion):
    factory = DBConnect.getConnection()
    query = factory(classname)
    requestIds = query.execute(criterion)
    reverseTypes, reverseStatus = reverseLookups()
    return [getRequest(requestId[0], reverseTypes, reverseStatus) for requestId in requestIds]

def getAssignmentsByName(requestName):
    request = getRequestByName(requestName)
    reqID = request['ReqMgrRequestID']
    assignments = getRequestAssignments(reqID)
    return [assignment['TeamName'] for assignment in assignments]


def getOverview():
    """
    _getOverview_

    Get the status, type and global queue info for all the request

    """
    factory = DBConnect.getConnection()
    getSummary = factory(classname = "Request.GetOverview")
    result = getSummary.execute()
    for request in result:
       getCampaign = factory(classname = "Campaign.GetByRequest")
       campaign = getCampaign.execute(request["request_id"])
       request["campaign"] = campaign
    return result

def getGlobalQueues():
    """
    _getGlobaQueues_

    Get list of Global Queues from request mgr db
    Convert Global Queue monitoring address to GlobalQueue
    Service address
    """
    factory = DBConnect.getConnection()
    getQueues = factory(classname = "Request.GetGlobalQueues")
    results = getQueues.execute()
    queues = []
    for url in results:
        queues.append(url.replace('workqueuemonitor', 'workqueue'))
    return queues


#!/usr/bin/env python

"""
ReqMgrRESTModel

This holds the methods for the REST model, all methods which
will be available via HTTP PUT/GET/POST commands from the interface,
the validation, the security for each, and the function calls for the
DB interfaces they execute.

https://twiki.cern.ch/twiki/bin/viewauth/CMS/ReqMgrSystemDesign
"""
import sys
import math
import cherrypy
import json
import threading
import urllib
import logging

import WMCore.Lexicon
from WMCore.Wrappers import JsonWrapper
from WMCore.WebTools.RESTModel import RESTModel
import WMCore.HTTPFrontEnd.RequestManager.ReqMgrWebTools as Utilities
from WMCore.WMException import WMException

import WMCore.RequestManager.RequestDB.Interface.User.Registration          as Registration
import WMCore.RequestManager.RequestDB.Interface.User.Requests              as UserRequests
import WMCore.RequestManager.RequestDB.Interface.Request.ListRequests       as ListRequests
import WMCore.RequestManager.RequestDB.Interface.Request.GetRequest         as GetRequest
import WMCore.RequestManager.RequestDB.Interface.Admin.RequestManagement    as RequestAdmin
import WMCore.RequestManager.RequestDB.Interface.Admin.ProdManagement       as ProdManagement
import WMCore.RequestManager.RequestDB.Interface.Admin.GroupManagement      as GroupManagement
import WMCore.RequestManager.RequestDB.Interface.Admin.UserManagement       as UserManagement
import WMCore.RequestManager.RequestDB.Interface.ProdSystem.ProdMgrRetrieve as ProdMgrRetrieve
import WMCore.RequestManager.RequestDB.Interface.Admin.SoftwareManagement   as SoftwareAdmin
import WMCore.RequestManager.RequestDB.Interface.Request.ChangeState        as ChangeState
import WMCore.RequestManager.RequestDB.Interface.Group.Information          as GroupInfo
import WMCore.RequestManager.RequestDB.Interface.Request.Campaign           as Campaign





class ReqMgrRESTModel(RESTModel):
    """ The REST interface to the ReqMgr database.  Documentation may
    be found at https://twiki.cern.ch/twiki/bin/viewauth/CMS/ReqMgrSystemDesign """
    def __init__(self, config):
        RESTModel.__init__(self, config)
        self.couchUrl = config.couchUrl
        self.workloadDBName = config.workloadDBName
        self.configDBName = config.configDBName
        self.wmstatWriteURL = "%s/%s" % (self.couchUrl.rstrip('/'), config.wmstatDBName)
        self.security_params = {'roles':config.security_roles}

        # Optional values for individual methods
        self.reqPriorityMax = getattr(config, 'maxReqPriority', 100)


        self._addMethod('GET', 'request', self.getRequest, 
                       args = ['requestName'],
                       secured=True, validation=[self.isalnum], expires = 0)
        self._addMethod('GET', 'assignment', self.getAssignment,
                       args = ['teamName', 'request'],
                       secured=True, validation = [self.isalnum], expires = 0)
        self._addMethod('GET', 'user', self.getUser,
                       args = ['userName'], 
                       secured=True, validation = [self.isalnum], expires = 0)
        self._addMethod('GET', 'group', self.getGroup,
                       args = ['group', 'user'], secured=True, expires = 0)
        self._addMethod('GET', 'version', self.getVersion, args = [], 
                        secured=True, expires = 0)
        self._addMethod('GET', 'team', self.getTeam, args = [], 
                        secured=True, expires = 0)
        self._addMethod('GET', 'workQueue', self.getWorkQueue,
                       args = ['request', 'workQueue'], 
                       secured=True, validation = [self.isalnum], expires = 0)
        self._addMethod('GET', 'message', self.getMessage,
                       args = ['request'], 
                       secured=True, validation = [self.isalnum], expires = 0)
        self._addMethod('GET', 'inputdataset', self.getInputDataset,
                       args = ['prim', 'proc', 'tier'],
                       secured=True)
        self._addMethod('GET', 'outputdataset', self.getOutputDataset,
                       args = ['prim', 'proc', 'tier'],
                       secured=True)
        self._addMethod('GET', 'campaign', self.getCampaign,
                       args = ['campaign'],
                       secured=True, validation = [self.isalnum], expires = 0)
        self._addMethod('PUT', 'request', self.putRequest,
                       args = ['requestName', 'status', 'priority'],
                       secured=True, validation = [self.isalnum, self.reqPriority])
        self._addMethod('PUT', 'assignment', self.putAssignment,
                       args = ['team', 'requestName'],
                       secured=True, security_params=self.security_params,
                       validation = [self.isalnum])
        self._addMethod('PUT', 'user', self.putUser,
                       args = ['userName', 'email', 'dnName'],
                       secured=True, security_params=self.security_params,
                       validation = [self.validateUser])
        self._addMethod('PUT', 'group', self.putGroup,
                       args = ['group', 'user'],
                       secured=True, security_params=self.security_params,
                       validation = [self.isalnum])
        self._addMethod('PUT', 'version', self.putVersion,
                       args = ['version', 'scramArch'],
                       secured=True, security_params=self.security_params,
                       validation = [self.validateVersion])
        self._addMethod('PUT', 'team', self.putTeam,
                       args = ['team'],
                       secured=True, security_params=self.security_params,
                       validation = [self.isalnum])
        self._addMethod('PUT', 'workQueue', self.putWorkQueue, 
                       args = ['request', 'url'],
                       secured=True, security_params=self.security_params,
                       validation = [self.validatePutWorkQueue])
        self._addMethod('PUT', 'message', self.putMessage,
                       args = ['request'],
                       secured=True, security_params=self.security_params,
                       validation = [self.isalnum])
        self._addMethod('PUT', 'campaign', self.putCampaign,
                       args = ['campaign', 'request'],
                       secured=True, 
                       validation = [self.isalnum])
        self._addMethod('POST', 'request', self.postRequest,
                        args = ['requestName', 'events_written', 
                                'events_merged', 'files_written',
                                'files_merged', 'percent_written', 
                                'percent_success', 'dataset'],
                        secured=True, validation = [self.validateUpdates])
        self._addMethod('POST', 'user', self.postUser,
                        args = ['user', 'priority'],
                        secured=True, security_params=self.security_params,
                        validation = [self.isalnum, self.intpriority])
        self._addMethod('POST',  'group', self.postGroup,
                        args = ['group', 'priority'],
                        secured=True, security_params=self.security_params,
                        validation = [self.isalnum, self.intpriority])
        self._addMethod('DELETE', 'request', self.deleteRequest,
                        args = ['requestName'],
                        secured=True, security_params=self.security_params,
                        validation = [self.isalnum])
        self._addMethod('DELETE', 'user', self.deleteUser,
                        args = ['user'],
                        secured=True, security_params=self.security_params,
                        validation = [self.isalnum])
        self._addMethod('DELETE', 'group', self.deleteGroup,
                        args = ['group', 'user'],
                        secured=True, security_params=self.security_params,
                        validation = [self.isalnum])
        self._addMethod('DELETE', 'version', self.deleteVersion,
                        args = ['version', 'scramArch'],
                        secured=True, validation = [self.validateVersion])
        self._addMethod('DELETE', 'team', self.deleteTeam,
                        args = ['team'],
                        secured=True, security_params=self.security_params,
                        validation = [self.isalnum])
        self._addMethod('DELETE', 'campaign', self.deleteCampaign,
                        args = ['campaign'],
                        secured=True, security_params=self.security_params,
                        validation = [self.isalnum])
        self._addMethod('GET', 'requestnames', self.getRequestNames,
                       args = [], secured=True, expires = 0)
        self._addMethod('GET', 'outputDatasetsByRequestName', self.getOutputForRequest,
                       args = ['requestName'], secured=True,
                       validation=[self.isalnum], expires = 0)
        self._addMethod('GET', 'outputDatasetsByPrepID', self.getOutputForPrepID,
                       args = ['prepID'], secured=True, 
                       validation=[self.isalnum], expires = 0)        
        self._addMethod('GET', 'mostRecentOutputDatasetsByPrepID', self.getMostRecentOutputForPrepID,
                       args = ['prepID'], secured=True, 
                       validation=[self.isalnum], expires = 0)
        self._addMethod('GET', 'configIDs', self.getConfigIDs, 
                        args = ['prim', 'proc', 'tier'],
                        secured=True, validation=[self.isalnum], expires = 0)

        cherrypy.engine.subscribe('start_thread', self.initThread)
    
    def initThread(self, thread_index):
        """ The ReqMgr expects the DBI to be contained in the Thread  """
        myThread = threading.currentThread()
        #myThread = cherrypy.thread_data
        # Get it from the DBFormatter superclass
        myThread.dbi = self.dbi

    def isalnum(self, index):
        """ Validates that all input is alphanumeric, 
            with spaces and underscores tolerated"""
        for v in index.values():
            WMCore.Lexicon.identifier(v)
        return index

    def getDataset(self, prim, proc, tier):
        """ If only prim exists, assume it's urlquoted.
            If all three exists, assue it's /prim/proc/tier 
        """
        if not proc and not tier:
            dataset = urllib.unquote(prim)
        elif prim and proc and tier:
            dataset = "/%s/%s/%s" % (prim, proc, tier)
        WMCore.Lexicon.dataset(dataset) 
        return dataset

    def intpriority(self, index):
        """ Casts priority to an integer """
        if index.has_key('priority'):
            value = int(index['priority'])
            if math.fabs(value) >= sys.maxint:
                msg = "Invalid priority!  Priority must have abs() less then MAXINT!" 
                raise cherrypy.HTTPError(400, msg)
            index['priority'] = value
        return index

    def reqPriority(self, index):
        """
        _reqPriority_

        Sets request priority to an integer.
        Also makes sure it's within a certain value.
        """
        if not index.has_key('priority'):
            return index
        
        index = self.intpriority(index = index)
        value = index['priority']
        if math.fabs(value) > self.reqPriorityMax and not Utilities.privileged():
            msg = "Invalid requestPriority!  Request priority must have abs() less then %i!" % self.reqPriorityMax
            raise cherrypy.HTTPError(400, msg)
            
        return index
    
    def validateUser(self, index):
        assert index['userName'].isalnum()
        assert '@' in index['email']
        assert index['email'].replace('@','').replace('.','').isalnum()
        if 'dnName' in index:
            assert index['dnName'].replace(' ','').isalnum()
        return index

    def validateVersion(self, index):
        """ Make sure it's a legitimate CMSSW version format """
        WMCore.Lexicon.cmsswversion(index['version'])
        return index

    def findRequest(self, requestName):
        """ Either returns the request object, or None """
        requests = ListRequests.listRequests()
        for request in requests:
            if request['RequestName'] == requestName:
                return request
        return None

    def getRequest(self, requestName=None):
        """ If a request name is specified, return the details of the request. 
        Otherwise, return an overview of all requests """
        if requestName == None:
            return GetRequest.getRequests()
        else:
            result = Utilities.requestDetails(requestName)
            try:
                teamNames = GetRequest.getAssignmentsByName(requestName)
                result['teams'] = teamNames
            except:
                # Ignore errors, then we just don't have a team name
                pass
            return result

    def getRequestNames(self):
        """ return all the request names in RequestManager as list """
        #TODO this could me combined with getRequest
        return GetRequest.getOverview()

    def getOutputForRequest(self, requestName):
        """Return the datasets produced by this request."""
        return Utilities.getOutputForRequest(requestName)

    def getOutputForPrepID(self, prepID):
        """Return the datasets produced by this prep ID. in a dict of requestName:dataset list"""
        requestIDs = GetRequest.getRequestByPrepID(prepID)
        result = {}
        for requestID in requestIDs:
            request = GetRequest.getRequest(requestID)
            requestName = request["RequestName"]
            helper = Utilities.loadWorkload(request)
            result[requestName] =  helper.listOutputDatasets()
        return result

    def getMostRecentOutputForPrepID(self, prepID):
        """Return the datasets produced by the most recently submitted request with this prep ID"""
        requestIDs = GetRequest.getRequestByPrepID(prepID)
        # most recent will have the largest ID
        requestIDs.sort()
        requestIDs.reverse()

        request = None
        # Go through each request in order from largest to smallest
        # looking for the first non-failed/non-canceled request
        for requestID in requestIDs:
            request = GetRequest.getRequest(requestID)
            rejectList = ['aborted', 'failed', 'rejected', 'epic-failed']
            requestStatus = request.get("RequestStatus", 'aborted').lower()
            if requestStatus not in rejectList:
                break

        if request != None:
            helper = Utilities.loadWorkload(request)
            return helper.listOutputDatasets()
        else:
            return []
 
    def getAssignment(self, teamName=None, request=None):
        """ If a team name is passed in, get all assignments for that team.
        If a request is passed in, return a list of teams the request is 
        assigned to 
        """
        # better to use ReqMgr/RequestDB/Interface/ProdSystem/ProdMgrRetrieve?
        #requestIDs = ProdMgrRetrieve.findAssignedRequests(teamName)
        # Maybe now assigned to team is same as assigned to ProdMgr
        result = []
        if teamName != None:
            requestIDs = ListRequests.listRequestsByTeam(teamName, "assigned").values()
            requests = [GetRequest.getRequest(reqID) for reqID in requestIDs]
            # put highest priorities first
            requests.sort(key=lambda r: r['RequestPriority'], reverse=True)
            # return list of tuples, since we need sorting
            result = [[req['RequestName'], req['RequestWorkflow']] for req in requests]
        elif request != None:
            result = GetRequest.getAssignmentsByName(request)
        return result


    def getUser(self, userName=None, group=None):
        """ No args returns a list of all users.  Group returns groups this user is in.  Username
            returs a JSON with information about the user """
        if userName != None:
            if not Registration.isRegistered(userName):
                raise cherrypy.HTTPError(404, "Cannot find user")
            result = {}
            result['groups'] = GroupInfo.groupsForUser(userName).keys()
            result['requests'] = UserRequests.listRequests(userName).keys()
            result['priority'] = UserManagement.getPriority(userName)
            result.update(Registration.userInfo(userName))
            return result
        elif group != None:
            GroupInfo.usersInGroup(group)    
        else:
            return Registration.listUsers()

        

    def getGroup(self, group=None, user=None):
        """ No args lists all groups, one args returns JSON with users and priority """
        if group != None:
            result = {}
            result['users'] =  GroupInfo.usersInGroup(group)
            try:
                result['priority'] = GroupManagement.getPriority(group)
            except IndexError:
                raise cherrypy.HTTPError(404, "Cannot find group/group priority")
            return result
        elif user != None:   
            return GroupInfo.groupsForUser(user).keys()
        else:
            return GroupInfo.listGroups()

    def getVersion(self):
        """ Returns a list of all CMSSW versions registered with ReqMgr """
        archList = SoftwareAdmin.listSoftware()
        result   = []
        for arch in archList.keys():
            for version in archList[arch]:
                if not version in result:
                    result.append(version)
        return result
      
    def getTeam(self):
        """ Returns a list of all teams registered with ReqMgr """
        return ProdManagement.listTeams()

    def getWorkQueue(self, request=None, workQueue=None):
        """ If a request is passed in, return the URl of the workqueue.
        If a workqueue is passed in, return all requests acquired by it """
        if workQueue != None:
            return ProdMgrRetrieve.findAssignedRequests(workQueue)
        if request != None:
            return ProdManagement.getProdMgr(request)
        # return all the workqueue ulr
        return GetRequest.getGlobalQueues()

    def getMessage(self, request):
        """ Returns a list of messages attached to this request """
        return ChangeState.getMessages(request)

    def getInputDataset(self, prim, proc=None, tier=None):
        """ returns a list of requests with this input dataset 
         Input can either be a single urlquoted dataset, or a 
         /prim/proc/tier"""
        dataset = self.getDataset(prim, proc, tier)
        return GetRequest.getRequestsByCriteria("Datasets.GetRequestByInput", dataset)  

    def getOutputDataset(self, prim, proc=None, tier=None):
        """ returns a list of requests with this output dataset 
         Input can either be a single urlquoted dataset, or a
         /prim/proc/tier"""
        dataset = self.getDataset(prim, proc, tier)
        return GetRequest.getRequestsByCriteria("Datasets.GetRequestByOutput", dataset)

    def getCampaign(self, campaign=None):
        """ returns a list of all campaigns if no argument, and a list of
             all requests in a campaign if there is an argument """
        if campaign == None:
            return Campaign.listCampaigns()
        else:
            return Campaign.listRequestsByCampaign(campaign)

    def putWorkQueue(self, request, url):
        """ Registers the request as "acquired" by the workqueue with the given URL """
        Utilities.changeStatus(request, "acquired", self.wmstatWriteURL)
        return ProdManagement.associateProdMgr(request, urllib.unquote(url))

    def validatePutWorkQueue(self, index):
        assert index['request'].replace('_','').replace('-','').replace('.','').isalnum()
        assert index['url'].startswith('http')
        return index

    def putRequest(self, requestName=None, status=None, priority=None):
        """ Checks the request n the body with one arg, and changes the status with kwargs """
        request = None
        if requestName:
            request = self.findRequest(requestName)
        if request == None:
            """ Creates a new request, with a JSON-encoded schema that is sent in the
            body of the request """
            body = cherrypy.request.body.read()
            schema = Utilities.unidecode(JsonWrapper.loads(body))
            schema.setdefault('CouchURL', Utilities.removePasswordFromUrl(self.couchUrl))
            schema.setdefault('CouchDBName', self.configDBName)
            try:
                request = Utilities.makeRequest(schema, self.couchUrl, self.workloadDBName, self.wmstatWriteURL)
            except cherrypy.HTTPError:
                # Assume that this is a valid HTTPError
                raise
            except WMException, ex:
                raise cherrypy.HTTPError(400, ex._message)
            except Exception, ex:
                raise cherrypy.HTTPError(400, ex.message)
        # see if status & priority need to be upgraded
        if status != None:
            # forbid assignment here
            if status == 'assigned' and request['RequestStatus'] != 'ops-hold':
                raise cherrypy.HTTPError(403, "Cannot change status without a team.  Please use PUT /reqmgr/rest/assignment/<team>/<requestName>")
            try:
                Utilities.changeStatus(requestName, status, self.wmstatWriteURL)
            except RuntimeError, e:
                # ignore some of these errors: https://svnweb.cern.ch/trac/CMSDMWM/ticket/2002
                if status != 'announced' and status != 'closed-out':
                    raise cherrypy.HTTPError(403, "Failed to change status: %s" % str(e))
        if priority != None:
            Utilities.changePriority(requestName, priority, self.wmstatWriteURL) 
        return request

    def putAssignment(self, team, requestName):
        """ Assigns this request to this team """
        # see if it's already assigned
        team = urllib.unquote(team)
        if not team in ProdManagement.listTeams():
            raise cherrypy.HTTPError(404,"Cannot find this team")
        requestNamesAndIDs = ListRequests.listRequestsByTeam(team)
        if requestName in requestNamesAndIDs.keys():
            raise cherrypy.HTTPError(400,"Already assigned to this team")
        return ChangeState.assignRequest(requestName, team)

    def putUser(self, userName, email, dnName=None):
        """ Needs to be passed an e-mail address, maybe dnName """
        if Registration.isRegistered(userName):
            return "User already exists"
        result = Registration.registerUser(userName, email, dnName)

    def putGroup(self, group, user=None):
        """ Creates a group, or if a user is passed, adds that user to the group """
        if(user != None):
            # assume group exists and add user to it
            return GroupManagement.addUserToGroup(user, group)
        if GroupInfo.groupExists(group):
            return "Group already exists"
        GroupManagement.addGroup(group)

    def putVersion(self, version, scramArch = None):
        """ Registers a new CMSSW version with ReqMgr """
        return SoftwareAdmin.addSoftware(version, scramArch = scramArch)

    def putTeam(self, team):
        """ Registers a team with ReqMgr """
        return ProdManagement.addTeam(urllib.unquote(team))

    def putMessage(self, request):
        """ Attaches a message to this request """
        message = JsonWrapper.loads( cherrypy.request.body.read() )
        result = ChangeState.putMessage(request, message)
        return result

    def putCampaign(self, campaign, request=None):
        """ Adds a campaign if it doesn't already exist, and optionally
            associates a request with it """
        if request:
            requestID = GetRequest.requestID(request)
            if requestID:
                result = Campaign.associateCampaign(campaign, requestID)
                Utilities.associateCampaign(campaign = campaign,
                                            requestName = request,
                                            couchURL = self.couchUrl,
                                            couchDBName = self.workloadDBName)
                return result
            else:
                return False
        else:
            Campaign.addCampaign(campaign)

        
#    def postRequest(self, requestName, events_written=None, events_merged=None, 
#                    files_written=None, files_merged = None, dataset=None):
    def postRequest(self, requestName, **kwargs):
        """
        Add a progress update to the request Id provided, params can
        optionally contain:
        - *events_written* Int
        - *events_merged*  Int
        - *files_written*  Int
        - *files_merged*   int
        - *percent_success* float
        - *percent_complete float
        - *dataset*        string (dataset name)
        """
        return ChangeState.updateRequest(requestName, kwargs)

    def validateUpdates(self, index):
        """ Check the values for the updates """
        for k in ['events_written', 'events_merged', 
                  'files_written', 'files_merged']:
            if k in index:
                index[k] = int(index[k])
        for k in ['percent_success', 'percent_complete']:
            if k in index:
                index[k] = float(index[k])
        return index

    def postUser(self, user, priority):
        """ Change the user's priority """
        return UserManagement.setPriority(user, priority)

    def postGroup(self, group, priority):
        """ Change the group's priority """
        return GroupManagement.setPriority(group, priority)

    def deleteRequest(self, requestName):
        """ Deletes a request from the ReqMgr """
        request = self.findRequest(requestName)
        if request == None:
            raise cherrypy.HTTPError(404, "No such request")
        return RequestAdmin.deleteRequest(request['RequestID'])

    def deleteUser(self, user):
        """ Deletes a user, as well as deleting his requests and removing
            him from all groups """
        if user in self.getUser():
            requests = json.loads(self.getUser(user))['requests']
            for request in requests:
                self.deleteRequest(request)
            for group in GroupInfo.groupsForUser(user).keys():
                GroupManagement.removeUserFromGroup(user, group)
            return UserManagement.deleteUser(user)

    def deleteGroup(self, group, user=None):
        """ If no user is sent, delete the group.  Otherwise, delete the user from the group """
        if user == None:
            return GroupManagement.deleteGroup(group)
        else:
            return GroupManagement.removeUserFromGroup(user, group) 

    def deleteVersion(self, version, scramArch):
        """ Un-register this software version with ReqMgr """
        SoftwareAdmin.removeSoftware(version, scramArch)

    def deleteTeam(self, team):
        """ Delete this team from ReqMgr """
        ProdManagement.removeTeam(urllib.unquote(team))

    def deleteCampaign(self, campaign):
        return Campaign.deleteCampaign(campaign)

    def getConfigIDs(self, prim, proc, tier):
        """
        _getConfigIDs_

        Get the ConfigIDs for the specified request
        """
        result = {}
        dataset = self.getDataset(prim, proc, tier)
        requests = GetRequest.getRequestsByCriteria("Datasets.GetRequestByInput", dataset)
        for request in requests:
            requestName = request["RequestName"]
            helper = Utilities.loadWorkload(request)
            result[requestName] = helper.listAllCMSSWConfigCacheIDs()

        return result



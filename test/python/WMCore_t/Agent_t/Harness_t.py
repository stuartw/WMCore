#!/usr/bin/env python
#pylint: disable-msg=E1101,C0103,R0902
"""
Component test TestComponent module and the harness
"""

__revision__ = "$Id: Harness_t.py,v 1.3 2008/10/01 11:09:13 fvlingen Exp $"
__version__ = "$Revision: 1.3 $"
__author__ = "fvlingen@caltech.edu"

import commands
import logging
import os
import threading
import unittest

from WMCore_t.Agent_t.TestComponent import TestComponent

from WMCore.Agent.Configuration import Configuration
from WMCore.Database.DBFactory import DBFactory
from WMCore.WMFactory import WMFactory

class HarnessTest(unittest.TestCase):
    """
    TestCase for TestComponent module 
    """

    _setup_done = False
    _teardown = False
    _log_level = 'debug'

    def setUp(self):
        """
        setup for test.
        """
        if not HarnessTest._setup_done:
            logging.basicConfig(level=logging.DEBUG,
                format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                datefmt='%m-%d %H:%M',
                filename='%s.log' % __file__,
                filemode='w')

            myThread = threading.currentThread()
            myThread.logger = logging.getLogger('HarnessTest')
            myThread.dialect = 'MySQL'

            options = {}
            options['unix_socket'] = os.getenv("DBSOCK")
            dbFactory = DBFactory(myThread.logger, os.getenv("DATABASE"), \
                options)

            myThread.dbi = dbFactory.connect()

            factory = WMFactory("msgService", "WMCore.MsgService."+ \
                myThread.dialect)
            create = factory.loadObject("Create")
            createworked = create.execute()
            if createworked:
                logging.debug("MsgService tables created")
            else:
                logging.debug("MsgService tables could not be created, \
                    already exists?")

            HarnessTest._setup_done = True

    def tearDown(self):
        """
        Delete database 
        """
        myThread = threading.currentThread()
        if HarnessTest._teardown and myThread.dialect == 'MySQL':
            command = 'mysql -u root --socket='\
            + os.getenv('TESTDIR') \
            + '/mysqldata/mysql.sock --exec "drop database ' \
            + os.getenv('DBNAME')+ '"'
            commands.getstatusoutput(command)

            command = 'mysql -u root --socket=' \
            + os.getenv('TESTDIR')+'/mysqldata/mysql.sock --exec "' \
            + os.getenv('SQLCREATE') + '"'
            commands.getstatusoutput(command)

            command = 'mysql -u root --socket=' \
            + os.getenv('TESTDIR') \
            + '/mysqldata/mysql.sock --exec "create database ' \
            +os.getenv('DBNAME')+ '"'
            commands.getstatusoutput(command)
        HarnessTest._teardown = False

    def testA(self):
        """
        Mimics creation of component and handles come messages.
        """
        # we want to read this from a file for the actual components.
        config = Configuration()
        config.Agent.contact = "fvlingen@caltech.edu"
        config.Agent.teamName = "Lakers"
        config.Agent.agentName = "Lebron James"

        config.section_("General")
        config.General.workDir = os.getenv("TESTDIR")

        config.component_("TestComponent")
        config.TestComponent.logLevel = 'DEBUG'

        config.section_("CoreDatabase")
        config.CoreDatabase.dialect = 'mysql' 
        config.CoreDatabase.socket = os.getenv("DBSOCK")
        config.CoreDatabase.user = os.getenv("DBUSER")
        config.CoreDatabase.passwd = os.getenv("DBPASS")
        config.CoreDatabase.hostname = os.getenv("DBHOST")
        config.CoreDatabase.name = os.getenv("DBNAME")

        testComponent = TestComponent(config)
        testComponent.prepareToStart()
        testComponent.handleMessage('LogState','')
        testComponent.handleMessage('TestMessage1','TestMessag1Payload')
        testComponent.handleMessage('TestMessage2','TestMessag2Payload')
        testComponent.handleMessage('TestMessage3','TestMessag3Payload')
        testComponent.handleMessage('TestMessage4','TestMessag4Payload')

        HarnessTest._teardown = True

    def runTest(self):
        """
        Tests the harness.
        """

        self.testA()

if __name__ == '__main__':
    unittest.main()


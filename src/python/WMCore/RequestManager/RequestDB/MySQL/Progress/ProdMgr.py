#!/usr/bin/env python
"""
_Progress.ProdMgr_

API for logging a ProdMgr that is associated with a request

"""



from WMCore.Database.DBFormatter import DBFormatter

class ProdMgr(DBFormatter):
    """
    _ProdMgr_

    """
    def execute(self, requestId, prodMgrName, conn = None, trans = False):
        """
        _execute_

        Associate requestId with the prodMgr Name provided

        """
        self.sql = "INSERT INTO reqmgr_assigned_prodmgr "
        self.sql += "(request_id, prodmgr_id) VALUES (:request_id, :prodmgr_name)" 
        binds = {"request_id": requestId, "prodmgr_name": prodMgrName}
        result = self.dbi.processData(self.sql, binds,
                                      conn = conn, transaction = trans)



#!/usr/bin/python
"""
_Lexicon_

A set of regular expressions  and other tests that we can use to validate input 
to other classes. If a test fails an AssertionError should be raised, and 
handled appropriately by the client methods, on success returns True. 
"""

__revision__ = "$Id: Lexicon.py,v 1.4 2009/10/14 17:38:30 metson Exp $"
__version__ = "$Revision: 1.4 $"

import re

def sitetier(candidate):
    return check("^T[0-3]", candidate)
    
def cmsname(candidate):
    """
    Check candidate as a (partial) CMS name. Should pass:    
        T2
        T2_UK
        T2_UK_SGrid
        T2_UK_SGrid_Bristol
    """
    #remove any trailing _'s
    candidate = candidate.rstrip('_')
    return check("^T[0-3%]((_[A-Z]{2})(_[A-Za-z]+)?)?", candidate)

def countrycode(candidate):
    #TODO: do properly with a look up table
    return check("^[A-Z]{2}$", candidate)

def check(regexp, candidate):
    assert re.compile(regexp).match(candidate) != None , \
              "'%s' does not match regular expression %s" % (candidate, regexp)
    return True
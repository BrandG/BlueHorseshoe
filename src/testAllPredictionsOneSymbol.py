#!/usr/bin/python

import sys
from datetime import timedelta
from myMongo import getEarliestDate
from myMongo import getLatestDate
from testOnePredictionOneSymbol import testOnePredictionOneSymbol
from myMongo import writeValidity

# This system takes all the dates available for a given symbol and builds the
# predictions for each symbol/date combination.


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getParameters() :
    if len(sys.argv) < 2:
        print "usage ./testAllPredictionsOneSymbol.py <<symbol>> "
        exit(0)
    return sys.argv[1]



symbol = getParameters()
startDate = getEarliestDate(symbol,10)
endDate = getEarliestDate(symbol,10) + timedelta(days=10)
#endDate = getLatestDate(symbol)
currentDate = startDate

successes = 0
failures = 0
while currentDate < endDate :
    currentDate = currentDate + timedelta(days=1)
    if currentDate.weekday() < 5:
        print currentDate
        result = testOnePredictionOneSymbol(currentDate.strftime("%Y-%m-%d"),symbol)
        if result == 1 :
            successes = successes+1
        elif result == 2 :
            failures = failures+1
        print "(success/failure) - ("+str(successes)+"/"+str(failures)+")"

        writeValidity(startDate,symbol,successes,failures)

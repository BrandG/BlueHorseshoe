#!/usr/bin/python

import sys
from pymongo import MongoClient
import pymongo
from datetime import datetime
from datetime import timedelta
from subprocess import call
import hashlib

# This system takes all the dates available for a given symbol and builds the
# predictions for each symbol/date combination.


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getParameters() :
    if len(sys.argv) < 2:
        print "usage ./testAllPredictionsOneSymbol.py <<symbol>> "
        exit(0)
    return sys.argv[1]

def getEarliestDate(symbol) :
    result = MongoClient().blueHorseshoe.history.find({"symbol" : symbol}).sort("date").limit(1)
    return datetime.strptime(result[0]["date"], '%Y-%m-%d')+timedelta(days=20)

def getLatestDate(symbol) :
    result = MongoClient().blueHorseshoe.history.find({"symbol" : symbol}).sort("date",-1).limit(1)
    return datetime.strptime(result[0]["date"], '%Y-%m-%d')


symbol = getParameters()
startDate = getEarliestDate(symbol)
endDate = getEarliestDate(symbol) + timedelta(days=20)
#endDate = getLatestDate(symbol)
currentDate = startDate

successes = 0
failures = 0
while currentDate < endDate :
    currentDate = currentDate + timedelta(days=1)
    if currentDate.weekday() < 5:
        print currentDate
        success=call(["/home/paperspace/BlueHorseshoe/src/testOnePredictionOneSymbol.py", symbol, currentDate.strftime("%Y-%m-%d")])
        if success == 1 :
            successes = successes+1
        elif success == 2 :
            failures = failures+1
        print "(success/failure) - ("+str(successes)+"/"+str(failures)+")"



MongoClient().blueHorseshoe.validity.replace_one( { "date" : startDate.strftime("%Y-%m-%d") ,
"symbol" : symbol }, {"_id" : str(int(hashlib.md5(startDate.strftime("%Y-%m-%d")+
symbol).hexdigest(),16)), "successes" : str(successes), "tests" : str(successes+failures) },
upsert=True )

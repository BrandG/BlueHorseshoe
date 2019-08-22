#!/usr/bin/python

import sys
from pymongo import MongoClient
import pymongo
from datetime import datetime
from datetime import timedelta
from subprocess import call

# This system takes all the dates available for a given symbol and builds the
# predictions for each symbol/date combination.


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getParameters() :
    if len(sys.argv) < 2:
        print "usage ./getStatsFromMonth.py <<symbol>> "
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
#endDate = getEarliestDate(symbol) + timedelta(days=1)
endDate = getLatestDate(symbol)
currentDate = startDate

while currentDate < endDate :
    currentDate = currentDate + timedelta(days=1)
    if currentDate.weekday() < 5:
        print currentDate
        call(["/home/paperspace/BlueHorseshoe/src/makeOnePredictionOneSymbol.py", symbol, currentDate.strftime("%Y-%m-%d")])

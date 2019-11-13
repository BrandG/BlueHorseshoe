#!/usr/bin/python

from datetime import timedelta
from myMongo import getEarliestDate
from myMongo import getLatestDate
from makeOnePredictionOneSymbol import makeOnePredictionOneSymbol

# This system takes all the dates available for a given symbol and builds the
# predictions for each symbol/date combination.


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getParameters() :
    if len(sys.argv) < 2:
        print "usage ./makeAllPredictionsOneSymbol.py <<symbol>> "
        exit(0)
    return sys.argv[1]


symbol = getParameters()
startDate = getEarliestDate(symbol,20)
endDate = getEarliestDate(symbol,20) + timedelta(days=140)
# endDate = getLatestDate(symbol)
currentDate = startDate

while currentDate < endDate :
    currentDate = currentDate + timedelta(days=1)
    if currentDate.weekday() < 5:
        print currentDate
        makeOnePredictionOneSymbol(currentDate.strftime("%Y-%m-%d"), symbol)

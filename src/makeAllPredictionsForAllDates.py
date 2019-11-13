#!/usr/bin/python

from datetime import timedelta
from myMongo import getEarliestDate
from myMongo import getLatestDate
from makeOnePredictionOneSymbol import makeOnePredictionOneSymbol

# This system takes all the dates available for a given symbol and builds the
# predictions for each symbol/date combination.


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
with open("/home/paperspace/BlueHorseshoe/data/symbollist.txt","r") as f :
    for symbolItem in f :
        symbol = symbolItem[:-1]
        print symbol
        startDate = getEarliestDate(symbol,10)
        endDate = getEarliestDate(symbol,10) + timedelta(days=10)
        #endDate = getLatestDate(symbol)
        currentDate = startDate

        while currentDate < endDate :
            currentDate = currentDate + timedelta(days=1)
            if currentDate.weekday() < 5:
                print currentDate
                makeOnePredictionOneSymbol(currentDate.strftime("%Y-%m-%d"), symbol)

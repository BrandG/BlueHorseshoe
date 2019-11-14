#!/usr/bin/python

import sys
from datetime import timedelta
from datetime import datetime
from myMongo import getEarliestDate
from myMongo import getLatestDate
from myMongo import writeValidity
from myMongo import getOneDate
from myMongo import getPrediction

# This system takes all the dates available for a given symbol and builds the
# predictions for each symbol/date combination.

def testOneDateOneSymbol(startDate, symbol) :
    success = 0
    failure = 0
    datetime_object = datetime.strptime(startDate, '%Y-%m-%d')
    dayOfWeek = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if datetime_object.weekday() < 5:
        correctResult = getOneDate(startDate, symbol)
        prediction = getPrediction(startDate, symbol)
        print dayOfWeek[datetime_object.weekday()] + " " + startDate

        if (correctResult != None) and (prediction != None) :
            print "high ("+str(prediction["predictionHigh"])+","+str(correctResult["high"])+") low (" + str(prediction["predictionLow"])+","+ str(correctResult["low"])+")"
            if (float(correctResult["high"]) > float(prediction["predictionHigh"])) and (float(correctResult["low"]) < float(prediction["predictionLow"])):
                return 1
            else :
                return 2
        return 0

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def testAllDatesOneSymbol(symbol):
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
            result = testOneDateOneSymbol(currentDate.strftime("%Y-%m-%d"),symbol)
            if result == 1 :
                successes = successes+1
            elif result == 2 :
                failures = failures+1
            print "(success/failure) - ("+str(successes)+"/"+str(failures)+")"

            writeValidity(startDate,symbol,successes,failures)


if __name__ == "__main__":
    """
    Main Function
    """
    if len(sys.argv) > 3 and sys.argv[1] == "all" and sys.argv[2] == "one":
        testAllDatesOneSymbol(sys.argv[3])
    if len(sys.argv) > 4 and sys.argv[1] == "one" and sys.argv[2] == "one":
        testOneDateOneSymbol(sys.argv[3],sys.argv[4])

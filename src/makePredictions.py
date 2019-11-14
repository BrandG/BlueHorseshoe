#!/usr/bin/python

import sys
from datetime import timedelta
from datetime import datetime
from myMongo import getEarliestDate
from myMongo import getLatestDate
from myMongo import getMonth
from myMongo import writePrediction

def predictAllDatesAllSymbols() :
    with open("/home/paperspace/BlueHorseshoe/data/symbollist.txt","r") as f :
        for symbolItem in f :
            symbol = symbolItem[:-1]
            print symbol
            allDatesOneSymbol(symbol)

def predictAllDatesOneSymbol(symbol) :
    startDate = getEarliestDate(symbol,20)
    endDate = getEarliestDate(symbol,20) + timedelta(days=140)
    # endDate = getLatestDate(symbol)
    currentDate = startDate

    while currentDate < endDate :
        currentDate = currentDate + timedelta(days=1)
        if currentDate.weekday() < 5:
            print currentDate
            oneDateOneSymbol(currentDate.strftime("%Y-%m-%d"), symbol)

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getStrength(daycount, monthData, halfDelta, midpointSlope) :
    strength = 0
    for i in range(daycount-1):
        day = monthData[i]
        nextMidpointGuess = ((float(day['high'])-float(day['low']))/2.0)+float(day['low'])+midpointSlope
        nextHighGuess=nextMidpointGuess+halfDelta
        nextLowGuess=nextMidpointGuess-halfDelta
        nextday = monthData[i+1]
        strength+=1 if nextHighGuess < float(nextday['high']) else 0
        strength+=1 if nextLowGuess > float(nextday['low']) else 0
    return strength


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getAverages(daycount, monthData) :
    averageHigh = 0
    averageLow = 0
    for i in range(daycount):
        day = monthData[i]
        averageHigh += float(day["high"])
        averageLow += float(day["low"])

    averageHigh /= float(daycount)
    averageLow /= float(daycount)
    return averageHigh, averageLow

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getMidpointSlope(daycount, monthData) :
    midpointSlope = 0
    testSlope = 0
    for i in range(daycount-1):
        day = monthData[i]
        nextday = monthData[i+1]
        # midpoint = (( high - low ) / 2 ) + low
        todayMidpoint = ((float(day['high'])-float(day['low'])) / 2.0) + float(day['low'])
        tomorrowMidpoint = ((float(nextday['high'])-float(nextday['low'])) / 2.0) + float(nextday['low'])
        midpointSlope += todayMidpoint - tomorrowMidpoint

    midpointSlope/=daycount - 1
    return midpointSlope


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def predictOneDateOneSymbol(startDate, symbol) :
    # Main functionality
    daycount = 20

    datetime_object = datetime.strptime(startDate, '%Y-%m-%d')
    dayOfWeek = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if datetime_object.weekday() < 5:
        print dayOfWeek[datetime_object.weekday()] + " " + startDate

        monthData = getMonth(startDate, symbol, daycount)
        if monthData == 0 :
            return

        midpointSlope = getMidpointSlope(daycount, monthData)

        averageHigh, averageLow = getAverages(daycount,monthData)
        standardDelta = averageHigh-averageLow

        standardDeltaPercent = standardDelta/float(monthData[daycount-1]['close'])*100.0
        halfDelta = standardDelta/2.0 #print 'delta'+" : {0: .2f}".format(deltaPercent)+"\t",

        strength = getStrength(daycount, monthData, halfDelta, midpointSlope) #print 'strength : '+str(strength)+"\t",

        # This gives the midpoint of the last day
        lastMidpoint = float(monthData[daycount-1]['close'])

        writePrediction(lastMidpoint+lastMidpoint*0.005, # half a percent above midpoint
            lastMidpoint-lastMidpoint*0.005,
            startDate,
            symbol,
            standardDeltaPercent,
            strength)

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--

if __name__ == "__main__":
    """
    Main Function
    """
    if len(sys.argv) > 2 and sys.argv[1] == "all" and sys.argv[2] == "all":
        predictAllDatesAllSymbols()
    if len(sys.argv) > 3 and sys.argv[1] == "all" and sys.argv[2] == "one":
        predictAllDatesOneSymbol(sys.argv[3])
    if len(sys.argv) > 4 and sys.argv[1] == "one" and sys.argv[2] == "one":
        predictOneDateOneSymbol(sys.argv[3],sys.argv[4])
#    testOnePredictionOneSymbol("1962-01-30","IBM")

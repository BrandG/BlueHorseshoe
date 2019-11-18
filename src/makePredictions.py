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
# This corresponds to the D column from the BlueHorseshoe sheet
#
def getDailyDeltas(daycount, monthData) :
    dailyDeltas = []
    for i in range(daycount) :
        dailyDeltas.append((float(monthData[i]['high'])-float(monthData[i]['low']))/2.0)
    return dailyDeltas


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
# This corresponds to the E column from the BlueHorseshoe sheet
#
def getMidpoints(daycount, monthData) :
    midpoints = []
    for i in monthData :
        midpoints.append((float(i['high'])+float(i['low']))/2.0)
    return midpoints


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
# This corresponds to the F column from the BlueHorseshoe sheet
#
def getMidpointDeltas(daycount, midpoints) :
    midpointDeltas = []
    for i in range(daycount-1) :
        midpointDeltas.append(midpoints[i+1]-midpoints[i])
    return midpointDeltas


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
# This corresponds to the last entry in the G column from the BlueHorseshoe sheet
#
def getTomorrowMidpoint(daycount, midpoints, midpointDeltas) :
    midpointAverage = 0.0
    for i in midpointDeltas :
        midpointAverage += i
    midpointAverage /= daycount
    return midpointAverage + midpoints[daycount-1]

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
# This corresponds to the final value of averageDelta from the BlueHorseshoe sheet
#
def getAverageDelta(daycount, dailyDeltas) :
    averageDelta = 0.0
    for i in dailyDeltas:
        averageDelta += i
    return averageDelta / daycount

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
# This corresponds to the final value of averageMidpoint from the BlueHorseshoe sheet
#
def getAverageMidpoint(daycount, midpoints) :
    averageMidpoint = 0.0
    for i in midpoints:
        averageMidpoint += i
    return averageMidpoint / daycount


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
        dailyDeltas = getDailyDeltas(daycount, monthData)
        midpoints = getMidpoints(daycount, monthData)
        midpointDeltas = getMidpointDeltas(daycount, midpoints)
        tomorrowMidpoint = getTomorrowMidpoint(daycount, midpoints, midpointDeltas)
        print "tomorrowMidpoint = "+str(tomorrowMidpoint)

        averageDelta = str(100.0*getAverageDelta(daycount, dailyDeltas)/getAverageMidpoint(daycount, midpoints))
        print "Average delta % = " + averageDelta

#         writePrediction(lastMidpoint+lastMidpoint*0.005, # half a percent above midpoint
#             lastMidpoint-lastMidpoint*0.005,
#             startDate,
#             symbol,
#             standardDeltaPercent,
#             strength)

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

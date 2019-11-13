#!/usr/bin/python

# getStatsFromMonth
# This program takes the month of data stored in /home/paperspace/BlueHorseshoe/data and returns a file with the next day's prediction (high and low), the average delta, and the strength (how often it is higher than the expected high and lower than the expected low).
# The prediction made will be stored with the previous day's date (it is the prediction made based on the month before the given date).
# So, if the day passed is x, then the prediction is made of the (daycount) days beforehand, and the prediction is for day x. The test takes the day passed and uses that day for both the prediction and the history.

from datetime import datetime
from datetime import timedelta
from myMongo import getMonth
from myMongo import writePrediction


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
def makeOnePredictionOneSymbol(startDate, symbol) :
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

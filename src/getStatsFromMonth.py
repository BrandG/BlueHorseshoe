#!/usr/bin/python

# getStatsFromMonth
# This program takes the month of data stored in /home/paperspace/BlueHorseshoe/data and returns a file with the next day's prediction (high and low), the average delta, and the strength (how often it is higher than the expected high and lower than the expected low).
# The prediction made will be stored with the previous day's date (it is the prediction made based on the month before the given date.

import json
from pymongo import MongoClient
import pymongo
import hashlib
import sys


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def readMonth(symbol, startDate) :
    # Note: We swap the dates, then swap them again because, when we ask for
    # "less than this date", we get the first entries in the DB, when what we
    # want is to have the last entries before that date. However, since we need
    # those entries in the oldest-to-youngest format, we have to reverse that
    # result

    #get a month of data
    result = MongoClient().blueHorseshoe.history.find({"date" : {"$lt" : startDate}, "symbol" : symbol}, {"_id":0,"date":1,"high":1,"low":1,"open":1,"close":1,"volume":1}).sort("date",-1).limit(20)

    #populate and reverse the array (based on date)
    readArray = []
    for document in range(20,0,-1) :
        readArray.append(result[document])
    return readArray, len(readArray) #    print readArray


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def writePrediction(predictionHigh, predictionLow, day, symbol, deltaPercent, strength) :
    print 'prediction : High {0: .2f}, Low {1: .2f}, Delta {2: 0.2f}%, Strength {3: 0.2f}'.format(predictionHigh,predictionLow,deltaPercent,strength)

    # print day
    idVal = str(int(hashlib.md5(str(day)).hexdigest(),16))
    try:
        MongoClient().blueHorseshoe.predictions.insert_one({"_id":idVal,"date" : day["date"], "symbol" : symbol, "delta" : deltaPercent, "strength" : strength, "predictionLow" : predictionLow, "predictionHigh" : predictionHigh})
    except pymongo.errors.DuplicateKeyError:
        print "Duplicate Entry"


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getStrength(daycount, monthData) :
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
def getAverages(daycount, monthData, average) :
    categories=['high','low','open','close','volume']
    for i in range(daycount):
        day = monthData[i]
        for category in categories:
            average[category] += float(day[category])

    for category in categories:
        average[category]/=float(daycount)

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
def getParameters() :
    if len(sys.argv) < 3:
        print "usage ./getStatsFromMonth.py <<symbol>> <<Year>>-<<Month>>-<<Day>>"
        exit(0)
    return sys.argv[1], sys.argv[2]



# Main functionality

symbol, startDate = getParameters() #"1998-10-01"

monthData, daycount = readMonth(symbol, startDate)

midpointSlope = getMidpointSlope(daycount, monthData)

average={'high':0, 'low':0, 'open':0, 'close':0, 'volume':0}
getAverages(daycount,monthData,average)

delta = average['high']-average['low']
deltaPercent = delta/float(monthData[daycount-1]['close'])*100.0
halfDelta = delta/2.0 #print 'delta'+" : {0: .2f}".format(deltaPercent)+"\t",

strength = getStrength(daycount, monthData) #print 'strength : '+str(strength)+"\t",

# This gives the midpoint of the last day
lastHalfDelta = (float(monthData[daycount-1]['high'])-float(monthData[daycount-1]['low']))/2.0
# This is the guess at where the midpoint tomorrow will be
predictionMidpoint = float(monthData[daycount-1]['low']) + lastHalfDelta + midpointSlope

writePrediction(predictionMidpoint+lastHalfDelta, #high value guess
    predictionMidpoint-lastHalfDelta, # low value guess
    monthData[daycount-1], # last day loaded
    symbol,
    deltaPercent,
    strength)

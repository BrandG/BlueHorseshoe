#!/usr/bin/python

# getStatsFromMonth
# This program takes the month of data stored in /home/paperspace/BlueHorseshoe/data and returns a file with the next day's prediction (high and low), the average delta, and the strength (how often it is higher than the expected high and lower than the expected low).
# The prediction made will be stored with the previous day's date (it is the prediction made based on the month before the given date.

import json
from pymongo import MongoClient
import pymongo
import hashlib
import sys


def getMonth(symbol, startDate) :
    #get a month of data
    result = MongoClient().blueHorseshoe.history.find({"date" : {"$lt" : startDate}, "symbol" : symbol}, {"_id":0,"date":1,"high":1,"low":1,"open":1,"close":1,"volume":1}).sort("date",-1).limit(20)

    #populate and reverse the array (based on date)
    readArray = []
    for document in range(20,0,-1) :
        readArray.append(result[document])
    print readArray
    return readArray

if len(sys.argv) < 3:
    print "usage ./getMonthFromDB.py <<symbol>> <<Year>>-<<Month>>-<<Day>>"
    exit(0)
symbol = sys.argv[1]
startDate = sys.argv[2] #"1998-10-01"


average={'high':0, 'low':0, 'open':0, 'close':0, 'volume':0}
lowest={'high':99999, 'low':99999, 'open':99999, 'close':99999, 'volume':99999}
categories=['high','low','open','close','volume']
midpointSlope = 0.0

monthData = getMonth(symbol, startDate)
daycount=len(monthData)
# Get averages for basic categories
for category in categories:
    for i in range(daycount):
        day = monthData[i]
        localValue = float(day[category])
        if lowest[category]>localValue: lowest[category] = localValue
        average[category]+=localValue

    average[category]/=float(daycount)

# Get Midpoint Slope
for i in range(daycount):
    if i < (daycount-1):
        day = monthData[i]
        nextday = monthData[i+1]
        currentMidpoint = ((float(day['high'])-float(day['low'])) / 2.0) + float(day['low'])
        nextMidpoint = ((float(nextday['high'])-float(nextday['low'])) / 2.0) + float(nextday['low'])
        midpointSlope += nextMidpoint-currentMidpoint
midpointSlope/=daycount - 1

delta = average['high']-average['low']
deltaPercent = delta/float(monthData[daycount-1]['close'])*100.0
halfDelta = delta/2.0

print 'delta'+" : {0: .2f}".format(deltaPercent)+"\t",

strength = 0
for i in range(daycount-1):
    day = monthData[i]
    nextday = monthData[i+1]
    nextMidpointGuess = ((float(day['high'])-float(day['low']))/2.0)+float(day['low'])+midpointSlope
    nextHighGuess=nextMidpointGuess+halfDelta
    nextLowGuess=nextMidpointGuess-halfDelta
    strength+=1 if nextHighGuess < float(nextday['high']) else 0
    strength+=1 if nextLowGuess > float(nextday['low']) else 0

print 'strength : '+str(strength)+"\t",

lastHigh = float(monthData[daycount-1]['high'])
lastLow = float(monthData[daycount-1]['low'])
lastHalfDelta = (lastHigh-lastLow)/2.0
lastMidpoint = lastHalfDelta+lastLow
predictionMidpoint = lastMidpoint + midpointSlope
predictionHigh=predictionMidpoint+lastHalfDelta
predictionLow=predictionMidpoint-lastHalfDelta

print 'prediction : {0: .2f} , {1: .2f}'.format(predictionHigh,predictionLow)

client = MongoClient()
db = client["blueHorseshoe"]
predictions = db["predictions"]
try:
    print monthData[daycount-1]
    idVal = str(int(hashlib.md5(str(monthData[daycount-1])).hexdigest(),16))
    result = predictions.insert_one({"_id":idVal,"date" : monthData[daycount-1]["date"], "symbol" : symbol, "delta" : deltaPercent, "strength" : strength, "predictionLow" : predictionLow, "predictionHigh" : predictionHigh})
except pymongo.errors.DuplicateKeyError:
    print "Duplicate Entry"

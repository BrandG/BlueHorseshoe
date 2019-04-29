#!/usr/bin/python

# getStatsFromMonth
# This program takes the month of data stored in /home/paperspace/BlueHorseshoe/data and returns a file with the next day's prediction (high and low), the average delta, and the strength (how often it is higher than the expected high and lower than the expected low).

import json

dataPath = "/home/paperspace/BlueHorseshoe/data/"
incomingJSON = 0
with open(dataPath+"getMonthFromDB.py.dat","r") as infile:
    infileData = infile.read()
    incomingJSON = json.loads(infileData)

average={'high':0, 'low':0, 'open':0, 'close':0, 'volume':0}
lowest={'high':99999, 'low':99999, 'open':99999, 'close':99999, 'volume':99999}
categories=['high','low','open','close','volume']
midpointSlope = 0.0
daycount=len(incomingJSON['days'])

# Get averages for basic categories
for category in categories:
    for i in range(daycount):
        day = incomingJSON['days'][i]
        localValue = float(day[category])
        if lowest[category]>localValue: lowest[category] = localValue
        average[category]+=localValue

    average[category]/=float(daycount)

# Get Midpoint Slope
for i in range(daycount):
    if i < (daycount-1):
        day = incomingJSON['days'][i]
        nextday = incomingJSON['days'][i+1]
        currentMidpoint = ((float(day['high'])-float(day['low'])) / 2.0) + float(day['low'])
        nextMidpoint = ((float(nextday['high'])-float(nextday['low'])) / 2.0) + float(nextday['low'])
        midpointSlope += nextMidpoint-currentMidpoint
midpointSlope/=daycount - 1

delta = average['high']-average['low']
deltaPercent = delta/float(incomingJSON['days'][daycount-1]['close'])*100.0
halfDelta = delta/2.0

print 'delta'+" : "+str(delta)+" : "+str(deltaPercent)+"%"

strength = 0
for i in range(daycount-1):
    day = incomingJSON['days'][i]
    nextday = incomingJSON['days'][i+1]
    nextMidpointGuess = ((float(day['high'])-float(day['low']))/2.0)+float(day['low'])+midpointSlope
    nextHighGuess=nextMidpointGuess+halfDelta
    nextLowGuess=nextMidpointGuess-halfDelta
    strength+=1 if nextHighGuess < float(nextday['high']) else 0
    strength+=1 if nextLowGuess > float(nextday['low']) else 0

print 'strength : '+str(strength)

lastHigh = float(incomingJSON['days'][daycount-1]['high'])
lastLow = float(incomingJSON['days'][daycount-1]['low'])
lastHalfDelta = (lastHigh-lastLow)/2.0
lastMidpoint = lastHalfDelta+lastLow
predictionMidpoint = lastMidpoint + midpointSlope
predictionHigh=predictionMidpoint+lastHalfDelta
predictionLow=predictionMidpoint-lastHalfDelta

print 'prediction : '+str(predictionHigh)+','+str(predictionLow)

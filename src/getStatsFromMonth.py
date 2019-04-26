#!/usr/bin/python

import json

dataPath = "/home/paperspace/BlueHorseshoe/data/"
incomingJSON = 0
with open(dataPath+"getMonthFromDB.py.dat","r") as infile:
    infileData = infile.read()
    incomingJSON = json.loads(infileData)
#print incomingJSON

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
    print category+" : "+str(average[category])

# Get Midpoint Slope
for i in range(daycount):
    if i < (daycount-1):
        day = incomingJSON['days'][i]
        nextday = incomingJSON['days'][i+1]
        currentMidpoint = ((float(day['high'])-float(day['low'])) / 2.0) + float(day['low'])
        print "low : "+str(day['low'])+"  high : "+str(day['high'])
        nextMidpoint = ((float(nextday['high'])-float(nextday['low'])) / 2.0) + float(nextday['low'])
        midpointSlope += nextMidpoint-currentMidpoint
        print "currentMid : "+str(currentMidpoint)+" NextMid : "+str(nextMidpoint)+" slope : "+str(midpointSlope)
midpointSlope/=daycount - 1

print 'delta'+" : "+str(average['high']-average['low'])+" : "+str((average['high']-average['low'])/float(incomingJSON['days'][daycount-1]['close'])*10.0)
print 'midpointSlope : '+str(midpointSlope)

#!/usr/bin/python

from datetime import datetime
import sys
import pymongo
from pymongo import MongoClient
from datetime import timedelta
from pprint import pprint


if len(sys.argv) < 3:
    print "usage ./testPrediction.py <<symbol>> <<Year-Month-Day>>"
    exit(0)

symbol = sys.argv[1]
startDate = sys.argv[2]

#dataPath = "/home/paperspace/BlueHorseshoe/data/"
blueHorseshoe = MongoClient().blueHorseshoe
predictionDB = blueHorseshoe.predictions
historyDB = blueHorseshoe.history

def getActual (sd, s, hDB) :
    print "For the date " + sd
    correctResult = hDB.find_one({"date" : sd, "symbol" : s}, {"_id":0,"date":1,"high":1,"low":1,"open":1,"close":1,"volume":1})
    print correctResult
    if correctResult == None :
        print "Invalid Date"
        return
    return correctResult


def getPrediction (sd, s, pDB) :
    print "\nPrediction from the date " + sd
    prediction = pDB.find_one({"date" : sd, "symbol" : s})
    print prediction
    if prediction == None :
        print "Invalid Date"
        return
    return prediction


success = 0
failure = 0
for i in range(40) :
    datetime_object = datetime.strptime(startDate, '%Y-%m-%d')
    newDate = datetime_object - timedelta(days=i)
    dayOfWeek = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if newDate.weekday() < 5:
        print dayOfWeek[newDate.weekday()]
        newDateString = newDate.strftime('%Y-%m-%d')
        correctResult = getActual(newDateString, symbol, historyDB)
        prediction = getPrediction(newDateString, symbol, predictionDB)

        if (correctResult != None) and (prediction != None) :
            if (float(correctResult["high"]) < float(prediction["predictionHigh"])) or (float(correctResult["low"]) > float(prediction["predictionLow"])):
                success += 1
                print "Success!!!"
            else :
                failure += 1
                print "failure"
        print ""
        print ""
        print ""

print "Successes = "+str(success)
print "Failures = "+str(failure)

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

print "For the date " + startDate
correctResult = historyDB.find_one({"date" : startDate, "symbol" : symbol}, {"_id":0,"date":1,"high":1,"low":1,"open":1,"close":1,"volume":1})
print correctResult
if correctResult == None :
    print "Invalid Date"
    sys.exit(0)

print "\nPrediction from the date " + startDate
prediction = predictionDB.find_one({"date" : startDate, "symbol" : symbol})
print prediction
if prediction == None :
    print "Invalid Date"
    sys.exit(0)

if (float(correctResult["high"]) < float(prediction["predictionHigh"])) or (float(correctResult["low"]) > float(prediction["predictionLow"])):
    print "Failed"
else:
    print "Success"

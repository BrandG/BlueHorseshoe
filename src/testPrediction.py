#!/usr/bin/python

from datetime import datetime
import sys
import pymongo
from pymongo import MongoClient
from datetime import timedelta
from pprint import pprint


dataPath = "/home/paperspace/BlueHorseshoe/data/"
client = MongoClient()
predictionDB = client.blueHorseshoe.predictions
historyDB = client.blueHorseshoe.history

if len(sys.argv) < 3:
    print "usage ./testPrediction.py <<symbol>> <<Year-Month-Day>>"
    exit(0)

symbol = sys.argv[1]
startDate = sys.argv[2]

datetime_object = datetime.strptime(startDate, '%Y-%m-%d')
newDate = datetime_object + timedelta(days=-1) # Note: We need to account for weekends here
newDateString = newDate.strftime('%Y-%m-%d')

print "For the date " + startDate

result = historyDB.find({"date" : startDate, "symbol" : symbol}, {"_id":0,"date":1,"high":1,"low":1,"open":1,"close":1,"volume":1})

correctResult = {}
for document in result:
    correctResult = document
    print(document)

print "Prediction from the date " + newDateString

result = predictionDB.find({"date" : newDateString, "symbol" : symbol})
for document in result:
    prediction = document
    print(document)

if (correctResult["high"] > prediction["predictionHigh"]) or (correctResult["low"] < prediction["predictionLow"]):
    print "Failed"
else:
    print "Success"

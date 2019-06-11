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
newDate = datetime_object + timedelta(days=20)
newDateString = newDate.strftime('%Y-%m-%d')

print newDateString

result = historyDB.find({"date" : {"$gte" : newDateString}, "symbol" : symbol}, {"_id":0,"date":1,"high":1,"low":1,"open":1,"close":1,"volume":1}).sort("date",1).limit(1)

correctResult = {}
for document in result:
    correctResult = document
    print(document)

#result = predictionDB.find({"date" :

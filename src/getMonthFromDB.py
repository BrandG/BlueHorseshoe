#!/usr/bin/python

# This code grabs from the BlueHorseshoe database, history collection.
# It gets 20 days prior to the date given.
# Given a specific date, the program will return 20 days worth of information
# with the date, high, low, open, close, and volume

import os
import csv
import hashlib
import json
from pymongo import MongoClient
import pymongo
import sys

if len(sys.argv) < 3:
    print "usage ./getMonthFromDB.py <<symbol>> <<Year>>-<<Month>>-<<Day>>"
    exit(0)
symbol = sys.argv[1]
startDate = sys.argv[2] #"1998-10-01"

#get a month of data
result = MongoClient().blueHorseshoe.history.find({"date" : {"$lt" : startDate}, "symbol" : symbol}, {"_id":0,"date":1,"high":1,"low":1,"open":1,"close":1,"volume":1}).sort("date",-1).limit(20)

#populate and reverse the array (based on date)
readArray = []
for document in range(20,0,-1) :
    readArray.append(result[document])
print readArray

#write out the array
with open("/home/paperspace/BlueHorseshoe/data/"+sys.argv[0]+".dat","w") as outfile:
    outfile.write("{\""+symbol+"\": [")
    documentCount = 0
    for document in readArray:
        tempResult=json.dumps(document)
        print tempResult
        outfile.write(tempResult)
        if documentCount < 19:
            outfile.write(",")
            documentCount += 1
    outfile.write("]}")

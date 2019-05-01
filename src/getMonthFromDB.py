#!/usr/bin/python

import os
import csv
import hashlib
import json
from pymongo import MongoClient
import pymongo
import sys

dataPath = "/home/paperspace/BlueHorseshoe/data/"
client = MongoClient()
db = client.blueHorseshoe

if len(sys.argv) < 3:
    print "usage ./getMonthFromDB.py <<symbol>> <<Year>>-<<Month>>-<<Day>>"
    exit(0)

symbol = sys.argv[1]
startDate = sys.argv[2] #"1998-10-01"

result = db.history.find({"date" : {"$gte" : startDate}, "symbol" : symbol}, {"_id":0,"date":1,"high":1,"low":1,"open":1,"close":1,"volume":1}).limit(20)
with open(dataPath+sys.argv[0]+".dat","w") as outfile:
    outfile.write("{\""+symbol+"\": [")
    documentCount = 19
    for document in result:
        tempResult=json.dumps(document)
        print tempResult
        outfile.write(tempResult)
        if documentCount > 0:
            outfile.write(",")
            documentCount -= 1
    outfile.write("]}")

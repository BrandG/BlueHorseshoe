#!/usr/bin/python

#ID,Date,Symbol,Open,High,Low,Close,Volume
#,"2015-08-03","SANM",27.650,28.820,25.720,27.740,000144700


import os
import csv
import hashlib
from pymongo import MongoClient
import pymongo

client = MongoClient()
db = client.blueHorseshoe

with open('/home/paperspace/BlueHorseshoe/data/backup.csv', 'r') as infile:
	reader = csv.DictReader(infile)
	for line in reader:
            try:
		linestring = line["date"]+" "+line["symbol"]
		idVal = str(int(hashlib.md5(linestring.encode('utf-8')).hexdigest(),16))
                print "id:"+idVal+"symbol:"+line["symbol"]+"date:"+line["date"]+"-open:"+str(line["open"])+"-close:"+str(line["close"])+"-high:"+str(line["high"])+"-low:"+str(line["low"])+"-volume:"+str(line["volume"])
                result = db.history.insert_one({"_id":idVal,"symbol":line['symbol'],"date":line['date'],"open":line['open'],"close":line['close'],"high":line['high'],"low":line['low'],"volume":line['volume']})
            except pymongo.errors.DuplicateKeyError:
                # skip document because it already exists in new collection
                continue

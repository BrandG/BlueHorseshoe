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
#    print "For the date " + sd
    correctResult = hDB.find_one({"date" : sd, "symbol" : s}, {"_id":0,"date":1,"high":1,"low":1})
#    print correctResult
    if correctResult == None :
        print "Invalid Date"
        return
    return correctResult


def getPrediction (sd, s, pDB) :
#    print "\nPrediction from the date " + sd
    prediction = pDB.find_one({"date" : sd, "symbol" : s})
    if prediction == None :
        print "Invalid Date"
        return
    return prediction


success = 0
failure = 0
datetime_object = datetime.strptime(startDate, '%Y-%m-%d')
dayOfWeek = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
if datetime_object.weekday() < 5:
    correctResult = getActual(startDate, symbol, historyDB)
    prediction = getPrediction(startDate, symbol, predictionDB)
    print dayOfWeek[datetime_object.weekday()] + " " + startDate

    if (correctResult != None) and (prediction != None) :
        print "high ("+str(prediction["predictionHigh"])+","+str(correctResult["high"])+") low (" + str(prediction["predictionLow"])+","+ str(correctResult["low"])+")"
        if (float(correctResult["high"]) > float(prediction["predictionHigh"])) and (float(correctResult["low"]) < float(prediction["predictionLow"])):
            print "Success!!!"
        else :
            print "failure"
    print ""

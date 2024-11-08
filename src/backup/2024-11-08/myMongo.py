#!/usr/bin/python

import pymongo
import hashlib
from datetime import datetime
from datetime import timedelta

db = pymongo.MongoClient().blueHorseshoe
historyColl = db.history
predictionColl = db.predictions
validityColl = db.validity

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def exportSymbolList():
    result = historyColl.find({}).distinct("symbol")
    with open("/home/paperspace/BlueHorseshoe/data/symbollist.txt","w") as f :
        for document in range(len(result)) :
            f.write(result[document]+"\n")

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getOneDate (sd, s) :
    correctResult = historyColl.find_one({"date" : sd, "symbol" : s}, {"_id":0,"date":1,"high":1,"low":1})
    if correctResult == None :
        print("Invalid Date")
        return
    return correctResult

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getEarliestDate(symbol,daycount) :
    result = historyColl.find({"symbol" : symbol}).sort("date").limit(1)
    return datetime.strptime(result[0]["date"], '%Y-%m-%d')+timedelta(days=daycount)

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getLatestDate(symbol) :
    result = pymongo.MongoClient().blueHorseshoe.history.find({"symbol" : symbol}).sort("date",-1).limit(1)
    return datetime.strptime(result[0]["date"], '%Y-%m-%d')

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def getPrediction (sd, s) :
    prediction = predictionColl.find_one({"date" : sd, "symbol" : s})
    if prediction == None :
        print("Invalid Date")
        return
    return prediction

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
    # Note: We swap the dates, then swap them again because, when we ask for
    # "less than this date", we get the first entries in the DB, when what we
    # want is to have the last entries before that date. However, since we need
    # those entries in the oldest-to-youngest format, we have to reverse that
    # result
def getMonth(sd,s,daycount) :
    result = historyColl.count_documents({"date" : {"$lte" : sd}, "symbol" : s})
    if int(result) < daycount+1 :
        return 0

    result = historyColl.find({"date" : {"$lte" : sd}, "symbol" : s}, {"_id":0,"date":1,"high":1,"low":1,"close":1}).sort("date",-1).limit(daycount)
    #populate and reverse the array (based on date)
    readArray = []

    for document in range(daycount,0,-1) :
        readArray.append(result[document])
    return readArray

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def writePrediction(predictionHigh, predictionLow, startDate, symbol, deltaPercent, strength) :
    # print 'prediction : High {0: .2f}, Low {1: .2f}, Delta {2: 0.2f}%, Strength {3: 0.2f}'.format(predictionHigh,predictionLow,deltaPercent,strength)

    idVal = str(int(hashlib.md5(startDate+symbol).hexdigest(),16))
    insertDict = {"_id":idVal,
        "date" : startDate,
        "symbol" : symbol,
        "delta" : deltaPercent,
        "strength" : strength,
        "predictionLow" : predictionLow,
        "predictionHigh" : predictionHigh}
    try:
        predictionColl.replace_one({"_id":idVal},insertDict,upsert=True)
    except pymongo.errors.DuplicateKeyError:
        print("Duplicate Entry")


#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
def writeValidity(startDate,symbol,successes,failures) :
    idVal = str(int(hashlib.md5(startDate.strftime("%Y-%m-%d")+symbol).hexdigest(),16))
    insertDict = {"_id":idVal,
        "date" : startDate,
        "symbol" : symbol,
        "successes" : str(successes),
        "tests" : str(successes+failures)}
    try:
        validityColl.replace_one({"_id":idVal},insertDict,upsert=True)
    except pymongo.errors.DuplicateKeyError:
        print ("Duplicate Entry")



#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--

if __name__ == "__main__":
    """
    Main Function
    """
#    print getMonth("1985-10-01","IBM",20)
#    print getPrediction("1985-10-01","IBM")
#    print getOneDate("1985-10-01","IBM")
#    exportSymbolList()

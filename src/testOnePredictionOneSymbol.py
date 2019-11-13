#!/usr/bin/python

from datetime import datetime
from myMongo import getOneDate
from myMongo import getPrediction

def testOnePredictionOneSymbol(startDate, symbol) :
    success = 0
    failure = 0
    datetime_object = datetime.strptime(startDate, '%Y-%m-%d')
    dayOfWeek = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if datetime_object.weekday() < 5:
        correctResult = getOneDate(startDate, symbol)
        prediction = getPrediction(startDate, symbol)
        print dayOfWeek[datetime_object.weekday()] + " " + startDate

        if (correctResult != None) and (prediction != None) :
            print "high ("+str(prediction["predictionHigh"])+","+str(correctResult["high"])+") low (" + str(prediction["predictionLow"])+","+ str(correctResult["low"])+")"
            if (float(correctResult["high"]) > float(prediction["predictionHigh"])) and (float(correctResult["low"]) < float(prediction["predictionLow"])):
                print "Success!!!"
            else :
                print "failure"
        print ""

if __name__ == "__main__":
    """
    Main Function
    """
#    testOnePredictionOneSymbol("1962-01-30","IBM")

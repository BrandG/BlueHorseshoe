#!/usr/bin/python

from pymongo import MongoClient

#//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--//==\\--
result = MongoClient().blueHorseshoe.history.find({}).distinct("symbol")
with open("/home/paperspace/BlueHorseshoe/data/symbollist.txt","w") as f :
    for document in range(len(result)) :
        f.write(result[document]+"\n")

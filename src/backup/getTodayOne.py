#!/usr/bin/python3
from pymongo import MongoClient
import requests
import json
import pprint

# There are three modes avaliable to grab data.
#    1) More than 20 years of data. This is done by calling alphaVantage with the "full" outputsize
#    2) Around five months. This is done by calling alphaVantage with the default outputsize ("compact")
#    3) One day. This is done by calling Yahoo.
#
# Note: None of these allow for multiple symbols to be queried. I still need to find a way to do that.



symbol="MSFT"

# //==\\==//==\\==//==\\==//==\\==     YAHOO

def getOneDay (symbol)
    path = "https://finance.yahoo.com/quote/MSFT?p=MSFT"
    r=requests.get(path)
    print (path)
    print (r.text)
#data=json.loads(r.text)
#print (data)
#TODO - Parse the yahoo data to get High,low,Open, and close
#TODO - Write parsed record to DB


# //==\\==//==\\==//==\\==//==\\==     ALPHA VANTAGE


def getMonths (symbol)
    getHistorical (symbol, "")

def getYears (symbol)
    getHistorical (symbol, "full")

#The default is to grab 100 data points (about 5 months). "Full" grabs more than 20 years of data.
def getHistorical (symbol, range)
    dataAmount=""
    if range=="full":
        dataAmount="&outputsize=full"
    path = "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol="+symbol+"&apikey=9F8T0SYSIZTWN06D"+dataAmount
    r=requests.get(path)
    print (path)
    print (r.text)
#data=json.loads(r.text)
#print (data)
#TODO - Parse JSON data to array of records
#TODO - Write parsed records to DB


#TODO - Maybe put in Google Finance?
#TODO - Find the historical system we used to use and see if that still works.


# # connect to MongoDB, change the << MONGODB URL >> to reflect your own connection string
# client = MongoClient('mongodb://localhost:27017/')
# db = client["Blue"]
# col = db["Horseshoe"]
#
# # col.insert_one({})
# print(client.list_database_names())
# print(db.list_collection_names())
# # col.find()
# bluedoc=col.find_one({},{"_id":0,"name":1})
# print(bluedoc)
#
# #https://www.alphavantage.co/
# #9F8T0SYSIZTWN06D <- API Key
#
# #cars = [ {'name': 'Audi', 'price': 52642},
# #    {'name': 'Mercedes', 'price': 57127},
# #    {'name': 'Skoda', 'price': 9000},
# #    {'name': 'Volvo', 'price': 29000},
# #    {'name': 'Bentley', 'price': 350000},
# #    {'name': 'Citroen', 'price': 21000},
# #    {'name': 'Hummer', 'price': 41400},
# #    {'name': 'Volkswagen', 'price': 21600} ]
# #
# #
# #with client:
# #    db = client.testdb
# #    db.cars.insert_many(cars)
# #
#
#

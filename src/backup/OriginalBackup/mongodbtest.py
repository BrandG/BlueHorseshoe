#!/usr/bin/python3
from pymongo import MongoClient
# pprint library is used to make the output look more pretty
from pprint import pprint
# connect to MongoDB, change the << MONGODB URL >> to reflect your own connection string
client = MongoClient('mongodb://localhost:27017/')
db = client.admin
# Issue the serverStatus command and print the results
serverStatusResult=db.command("serverStatus")
pprint(serverStatusResult)

#cars = [ {'name': 'Audi', 'price': 52642},
#    {'name': 'Mercedes', 'price': 57127},
#    {'name': 'Skoda', 'price': 9000},
#    {'name': 'Volvo', 'price': 29000},
#    {'name': 'Bentley', 'price': 350000},
#    {'name': 'Citroen', 'price': 21000},
#    {'name': 'Hummer', 'price': 41400},
#    {'name': 'Volkswagen', 'price': 21600} ]
#
#
#with client:
#    db = client.testdb
#    db.cars.insert_many(cars)
#



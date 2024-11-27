#!/usr/bin/python3
import requests
import json

r=requests.get("https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=MSFT&apikey=9F8T0SYSIZTWN06D")
data=json.loads(r.text)
print (data)


#https://www.alphavantage.co/
#9F8T0SYSIZTWN06D <- API Key

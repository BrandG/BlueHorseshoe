#!/usr/bin/python

import pymysql
import sys
from subprocess import call
from datetime import date
import datetime
import requests
import hashlib
from requests.packages.urllib3.util import Retry
from requests.adapters import HTTPAdapter
from requests import Session, exceptions

# static paths
dataHome = "/blueHorseshoe/"
csvHome = dataHome+"csvs/"
jsonHome = dataHome+"json/"
csvFileName = dataHome+"currentCSV.csv"
allSymbolsFile = dataHome+"allSymbols.txt"

if len(sys.argv)<2 :
        print "First parameter should be the number of years to grab"
        sys.exit()

yearsToGrab = int(sys.argv[1])

cnx = pymysql.connect(user='root', password='8r4Nd0Ng',
                              host='127.0.0.1',
                              database='blueHorseshoe',
				autocommit=True)
cur = cnx.cursor(pymysql.cursors.DictCursor)

# get the latest symbols
call(["/usr/bin/python","/blueHorseshoe/getSymbolList.py"])

# re-initialize the stats file
call(["rm","stats.txt"])
statsFile = open(dataHome+"stats.txt","a",0)

# open files to be used for processing
outFile = open(dataHome+"allHistoricalData.csv","w")
errFile = open(dataHome+"error.txt","w")

# initialize our date variables
today = date.today()
month = str(today.month)
day = str(today.day)
lastYear = str(today.year)
firstYear = str(today.year - yearsToGrab)
with open(allSymbolsFile, "r") as ins:
        for line in ins:
                singleSymbol = line.split("|")[0][:-1]
                statsFile.write("Symbol - "+singleSymbol+" : Time - "+str(datetime.datetime.now().time())+"\n")
                if "File Creation Time" not in singleSymbol and "Symbol|Security Name" not in line:
                        payload = { 's' : singleSymbol, 'd' : month, 'e' : day, 'f' : lastYear, 'g':'d', 'a':month, 'b':day, 'c':firstYear, 'ignore':'.csv' }
                        headers = {}
                        url     = "http://real-chart.finance.yahoo.com/table.csv"
                        s = requests.Session()
			s.mount('http://', HTTPAdapter( max_retries=Retry(total=5, status_forcelist=[500, 503])))
                        r=s.get(url, params=payload, headers=headers, timeout=None)
                        print r.url
			if r.status_code == requests.codes.ok :
				for result in r.text.split('\n'):
					parsed = result.split(',')
#					print "Result = "+result
					if len(parsed) < 5 or parsed[0]=="Date":
						continue
					querystring = "INSERT INTO history(`id`,`date`,`symbol`,`open`,`close`,`high`,`low`,`volume`) VALUES ("
					linestring = singleSymbol+parsed[0]+parsed[1]+parsed[2]+parsed[3]+parsed[4]+parsed[5]
					idVal = str(hashlib.md5((singleSymbol+result).encode('utf-8')).hexdigest())
					querystring += "'"+idVal+"','"+parsed[0]+"','"+singleSymbol+"',"+parsed[1]+","+parsed[4]+","+parsed[2]+","+parsed[3]+","+parsed[5]+")"
					print querystring
#					cur.execute(querystring)
#					if (mysql_errno() == 1062) {
#					    print 'no way!';
#					}
					try:
					    cur.execute(querystring)
					    cnx.commit()
					except pymysql.IntegrityError as e:
					    if not e[0] == 1062:
						raise
					    else:
						print "MY ERROR 1062: " + e[1]
			else:
				errFile.write(singleSymbol+"\n")
errFile.close()
outFile.close()
statsFile.close()

#cur.execute("INSERT INTO history(`id`,`date`,`symbol`,`open`,`close`,`high`,`low`,`volume`) VALUES ('4','2017-01-05','AAPL',100.00,110.00,110.00,100.00,1000000)")


## print it out
#UserId = 'AAPL'
#sql = "SELECT date FROM history WHERE symbol ='%s'"
#cur.execute(sql % UserId)
#for row in cur:
#    print(row['date'])
cnx.close()

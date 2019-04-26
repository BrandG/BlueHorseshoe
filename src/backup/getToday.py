#!/usr/bin/python

# http://download.finance.yahoo.com/d/quotes.csv?s=AAPL,HSY&f=sl1d1t1c1ohgv&e=.csv

import os
import datetime
from subprocess import check_call

maxSymbols = 1500
dataHome = "/home/brand/"

symbols = []
groupCount = 0
totalCount = 0
with open(dataHome+"todaysData.txt", "w") as outFile:
	with open(dataHome+"allSymbols.txt", "r") as ins:
		for line in ins:
			singleSymbol = line.split("|")[0][:-1]
			if "Symbol" in singleSymbol:
				continue
			totalCount += 1
			symbols.append(line.split("|")[0][:-1])
			if len(symbols) > maxSymbols:
				print "File today"+str(groupCount)+".txt"
				print symbols
				check_call(["curl","-otoday.txt", "http://download.finance.yahoo.com/d/quotes.csv?s="+",".join(symbols)+"&f=sl1d1t1c1ohgv&e=.csv"])
				with open("today.txt","r") as todayfile:
					for todaysLine in todayfile:
						outFile.write(todaysLine)
#				check_call(["rm","today.txt"])
				groupCount += 1
				symbols = []
	print symbols
	check_call(["curl","-otoday.txt", "http://download.finance.yahoo.com/d/quotes.csv?s="+",".join(symbols)+"&f=sl1d1t1c1ohgv&e=.csv"])
	with open("today.txt","r") as todayfile:
		for todaysLine in todayfile:
			outFile.write(todaysLine)
	check_call(["rm","today.txt"])
print "TotalCount = "+str(totalCount)

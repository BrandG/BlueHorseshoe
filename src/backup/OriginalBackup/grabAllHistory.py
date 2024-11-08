#!/usr/bin/python

from subprocess import call

with open("onlySymbols.txt", "r") as ins:
    for line in ins:
	symbol = line[:-1]
	parameters = "http://real-chart.finance.yahoo.com/table.csv?s="+symbol+"&d=6&e=12&f=2016&g=d&a=3&b=12&c=1996&ignore=.csv"
	print parameters
	call(["curl", "-o"+symbol+".csv", parameters ])
#curl -o yhoo.csv http://real-chart.finance.yahoo.com/table.csv?s=yhoo&d=6&e=12&f=2016&g=d&a=3&b=12&c=1996&ignore=.csv
#	print 'http://real-chart.finance.yahoo.com/table.csv?s='+line[:-1]+'&d=6&e=12&f=2016&g=d&a=3&b=12&c=1996&ignore=.csv'

#!/usr/bin/python

import os
import datetime
import csv
import string
from subprocess import call

dataHome = "/home/brand/"
outputHome = dataHome+"/secondoutput/"
allSymbolsFile = dataHome+"allHistoricalData.csv"

with open(allSymbolsFile, 'r') as infile:
	reader = csv.DictReader(infile)
	currentSymbol = ""
	for line in reader:
		try:
			if len(''.join(c for c in line['Date'] if c in string.ascii_letters)) > 0 or \
			len(''.join(c for c in line['Date'] if c == '*')) > 0:
				continue
			openVal = float(line['Open'])

			if currentSymbol != line['AAAP']:
				currentSymbol = line['AAAP']
				if 'outfile' in locals():
					outfile.close()
				symbol = line['AAAP']
				print symbol
				outfile = open(outputHome+symbol+".csv", 'a')
				writer = csv.writer(outfile)
				writer.writerow(["Symbol", "Year", "Month", "Day", "Open", "High", "Low", "Close", "Volume"])

			splitDate = line['Date'].split('-')
			
			writer.writerow([line['AAAP'], splitDate[0]+"-"+splitDate[1]+"-"+splitDate[2], "{:5.3f}".format(openVal), "{:5.3f}".format(float(line['High'])), "{:5.3f}".format(float(line['Low'])), "{:5.3f}".format(float(line['Close'])), "{:09d}".format(int(line['Volume']))])
		except ValueError:
			print line
			print "Not a float"



	#	splitline=line.split(",")
	#	singleSymbol = line.split("|")[0]+'\n'
#	print singleSymbol

#I use AAAP as the Symbol label, because that's what was written into the CSV. I'd change it if I could, but it's a 1.2Gig file, so it's a little hard to edit.

#call(["curl","-o"+dataHome+"symbolList.txt", "ftp.nasdaqtrader.com/SymbolDirectory/otherlisted.txt"])

#with csv.reader(open(allSymbolsFile, 'r')) as infile, csv.writer(open(outputFileName, 'w')):

#AAAP,Date,Open,High,Low,Close,Volume,Adj Close
#AAAP,2016-07-22,30.549999,30.690001,30.360001,30.51,18000,30.51
#allHistoricalData.csv

#			print "Symbol = {}, Date ({}/{}/{}), Open = {}, High = {}, Low = {}, Close = {}, Volume = {}".format(line['AAAP'], line['Date'].split('-')[0], line['Date'].split('-')[1], line['Date'].split('-')[2], line['Open'], line['High'], line['Low'], line['Close'], line['Volume'])

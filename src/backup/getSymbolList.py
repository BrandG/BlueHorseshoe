#!/usr/bin/python

import os
import datetime
from subprocess import call

dataHome = "/home/paperspace/BlueHorseshoe/data/"
allSymbolsFile = dataHome+"allSymbols.txt"

call(["curl","-o"+dataHome+"symbolList1.txt", "ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt"])
call(["curl","-o"+dataHome+"symbolList.txt", "ftp.nasdaqtrader.com/SymbolDirectory/otherlisted.txt"])
filenames = [dataHome+'symbolList1.txt', dataHome+'symbolList.txt']
with open(allSymbolsFile, 'w') as outfile:
    for fname in filenames:
        with open(fname) as infile:
            for line in infile:
		singleSymbol = line.split("|")[0]+'\n'
		if "Creation Time" not in singleSymbol and "Symbol" not in singleSymbol and '.' not in singleSymbol and not '$' in singleSymbol:
			outfile.write(singleSymbol)
call(["rm",dataHome+'symbolList1.txt'])
call(["rm",dataHome+'symbolList.txt'])

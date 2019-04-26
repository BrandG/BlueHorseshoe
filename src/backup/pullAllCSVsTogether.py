#!/usr/bin/python

import os
from subprocess import call

outFile = open("allHistoricalData.csv","w")
for file in os.listdir("/home/brand/csvs/"):
	if file.endswith(".csv"):
		print(file)
		with open ("/home/brand/csvs/"+file, "r") as csvFile:
			for line in csvFile:
				outFile.write(file[:-4]+','+line)
outFile.close()

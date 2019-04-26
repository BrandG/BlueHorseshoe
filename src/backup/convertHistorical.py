#!/usr/bin/python

# This takes a json file (first parameter) and converts it to a mongo-compatable json file.

import os
import datetime
import string
import hashlib
import sys
from subprocess import check_call

dataHome = "/blueHorseshoe/"
infileName = sys.argv[1]
outfileName = sys.argv[1]+".json"
dateString = datetime.datetime.now().strftime('%m-%d-%Y')
statsFileName = dataHome+"stats"+dateString+".txt"

def addOneJSONelement(key,value):
	return ", \""+key+"\":\""+value+"\""

with open(outfileName, 'w') as outfile, open(infileName,'r') as infile, open(statsFileName,'a') as statsfile:
	for line in infile:
		lineSplit = line.split(",")
		if lineSplit[0] == "Symbol":
			continue
		statsfile.write("attempting to convert -> "+line)
		if len(lineSplit) < 6:
			print "Check this out ->",
			print lineSplit
			statsfile.write("invalid symbol")
		else:
			volumeString = "{}".format(int(lineSplit[6]))[:-1]
			outline = "{ \"_id\":\""
			outline += str(int(hashlib.md5(line.encode('utf-8')).hexdigest(),16))+"\""
			outline += addOneJSONelement("date",lineSplit[1])
			outline += addOneJSONelement("symbol",lineSplit[0])
			outline += addOneJSONelement("close",lineSplit[5])
			outline += addOneJSONelement("open",lineSplit[2])
			outline += addOneJSONelement("high",lineSplit[3])
			outline += addOneJSONelement("low",lineSplit[4])
			#outline += addOneJSONelement("volume",lineSplit[6].translate(string.maketrans("",""), string.punctuation))
			outline += addOneJSONelement("volume",volumeString)
			outline += "}\n"
			print outline,
			outfile.write(outline)

#check_call("mongoimport --db test --collection history --drop --file "+outfileName, shell=True)

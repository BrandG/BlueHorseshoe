#!/usr/bin/python


symbolList = []
with open("error.txt","r") as errFile:
	for errline in errFile:
		symbolList.append(errline.split(" - ")[1][:-1])
with open("allSymbols.txt","r") as inFile:
	with open("cleanedSymbols.txt","w") as outFile:
		count = 0
		for inline in inFile:
			if inline[:-1] not in symbolList:
				outFile.write(inline)

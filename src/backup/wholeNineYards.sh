#!/bin/bash

export BRAND_HOME="/home/brand"
curl ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt > $BRAND_HOME/symbolList.txt 
curl ftp.nasdaqtrader.com/SymbolDirectory/otherlisted.txt >> $BRAND_HOME/symbolList.txt
/home/brand/grabSymbolsAndCSVs.py

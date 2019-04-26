#This one calls convertHistorical on all files 
#for f in /blueHorseshoe/oldOutput/*.csv; do /blueHorseshoe/convertHistorical.py $f ; done
#This one moves all .next files back into their original name.
#for f in /blueHorseshoe/oldOutput/*.csv; do rm $f ; mv $f.next $f ; done
#This one adds a new extension to each file
for f in /blueHorseshoe/json/*; do mv $f $f.json ; done
#This one removes the last extension from each file
#for f in /blueHorseshoe/json/*; do mv $f ${f%.*} ; done
#this one adds the standard header to all the files :
#for f in /blueHorseshoe/oldOutput/*.csv; do echo "Symbol, Date, Open, High, Low, Close, Volume" > $f.next ; cat $f >> $f.next ; done
#This one removes the last line from a file:
#for f in /blueHorseshoe/oldOutput/*.csv; do head -n -1 $f > brandtemp ; mv brandtemp $f.next ; done
#This one removes the first line from a file:
#for f in /blueHorseshoe/oldOutput/*.csv; do tail -n +2 $f > brandtemp ; mv brandtemp $f.next ; done
#This one imports all json files to mongo
for f in /blueHorseshoe/json/*.json; do mongoimport --db blueHorseshoe --collection history --file $f ; done

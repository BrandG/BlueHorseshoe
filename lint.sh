pylint ./src/*.py > linting.txt
cat linting.txt | sort > linting_sorted.txt
rm linting.txt

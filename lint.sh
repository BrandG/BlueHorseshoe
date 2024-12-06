date
pylint ./src/*.py ./src/indicators/*.py > linting.txt
cat linting.txt | sort > linting_sorted.txt
rm linting.txt
date

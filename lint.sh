#!/bin/bash
date
pylint $(find src -name "*.py") > linting.txt
date
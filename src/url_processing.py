#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CSV file phshing link data extraction 

Reads the csv and prints the rows as dictionary

How to use it:
    python url_preprocessing.py 

"""

# import necessary libraries
import csv
#import urllib3
import os, time
from posix import listdir


input_directory = str(input("provide the directory that the csv is located: "))

def find_the_file(input):
    for filename in os.listdir(input_directory):
        if filename.startswith("PHISHING") and filename.endswith(".xlsx"):
            pass






"""Readers for public sources that are not one city's own: the state's and the nation's open data.

Each reader is a plain function that returns plain data and names its source. Every request goes through
fetch.py, so the offline tests can stand in for the network in one place.
"""

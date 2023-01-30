import random

def generateRandomId(prefix):
    integer = random.randint(10000000, 99999999)
    return prefix + str(integer)
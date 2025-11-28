from sec100Client import sec100Client
import sys
import os
import time

ip = "192.168.136.100"
password = "servicelevel"
user = "Service"


sec100 = sec100Client(ip, user, password)

sec100.setSnapshotMode(1)
sec100.triggerSnapshot()
time.sleep(1)
sec100.downloadLatestSnapshot('latestSnapshot.jpeg')

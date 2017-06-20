# GPSTrackerClient
Client side code for the GPSTracker framework

# Preconditions
This Tracker client is compatible with all GPS recievers that use the linux GPSD daemon.
You must make sure that GPSD is up and running before running the code.
You must have network connectivity at some point to be able to upload the GPS data to the server. The failed uploads will be stored on the storage of your device until sucsessful upload.
Constant network connectivity is preferred, but not necessary.


# Installing on Raspberry PI 3 model B
(optional) Remove unnecessary services like "avahi"
1. Install and set up your GPS reciever on Raspberry PI
	a, make sure your GPS device is supported by the OS you are running, OR have your kernel modules ready and installed.
		The Raspbian Os has pretty good coverage in terms of usb-serial converters. PL2303 was tested and works out of the box.
		https://www.raspberrypi.org/downloads/raspbian/
	b, Install gpsd: sudo apt-get install gpsd gpsd-clients python-gps

2. Install git and pip
	a, sudo apt install git python-pip
	
3. Install necessary python packages
	pip install requests
	
3. Clone this repo
	a, git clone https://github.com/skelsec/GPSTrackerClient.git
	
4. Edit the config file
	a, modify "UPLOAD_URL" to point to your server
	
5. Start up the script for a test
	a, python gpsTracker.py -c config.json
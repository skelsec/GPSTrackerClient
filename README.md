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
	a, cd /opt
	b, git clone https://github.com/skelsec/GPSTrackerClient.git
	
4. Edit the config file
	a, modify "UPLOAD_URL" to point to your server
	b, modify the startClient.sh script to point to your files (if not using it from /opt/)

5. Start up the script for a test
	a, python gpsTracker.py -c config.json
	b, check syslog (tail -f /var/log/syslog) if the script tries to upload some data then it means it is working
6. Edit crontab to start up your tracker client script on boot. This example will check if your script is still running eevery minute, and start it otherwise
	a, crontab -e
	b, in the editor add the following line (modify the path if needed) "* * * * * /usr/bin/flock -n /tmp/fcj.lockfile -c /opt/GPSTrackerClient/startClient.sh --minutely"
		
7. restart your raspberry and check in syslog if the script is uploading data.

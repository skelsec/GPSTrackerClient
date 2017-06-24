#!/usr/bin/env python
import time
import threading
import multiprocessing
import cStringIO
import gzip
from datetime import datetime
import glob
import os
import json
import shutil

import logging
import logging.handlers

import gps
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

class DictWrapperEncoder(json.JSONEncoder):
	def default(self, obj):
		if isinstance(obj, gps.dictwrapper):
			return dict(obj)
		
		return json.JSONEncoder.default(self.obj)

class GPSPoller(multiprocessing.Process):
	def __init__(self, reportQueue, logQueue, config):
		multiprocessing.Process.__init__(self)
		self.reportQueue = reportQueue
		self.logQueue = logQueue
		self.gpsd = ''
		
	def setup(self):
		self.gpsd = gps.gps()
		self.gpsd.stream(gps.WATCH_ENABLE|gps.WATCH_NEWSTYLE)

	def log(self, level, message):
		self.logQueue.put((level, self.name, message))
		
	def run(self):
		try:
			self.setup()
		except Exception as e:
			self.log('EXCEPTION','Error when setting up GPS polling! Data: %s' % (e))
			return
			
		self.log('DEBUG','Setup complete!')
			
		while True:
			try:
				for gpsdata in self.gpsd:
					self.reportQueue.put(json.dumps(gpsdata, cls=DictWrapperEncoder))
			except Exception as e:
				self.log('EXCEPTION','Error when setting up GPS polling! Data: %s' % (e))
				return
				
		self.log('DEBUG','Terminating!')

class Logger(multiprocessing.Process):
	def __init__(self, logQueue, config):
		multiprocessing.Process.__init__(self)
		self.logQueue = logQueue
		self.config = config
		self.logger = ''
		
	def setup(self):
	
		self.logger = logging.getLogger(self.config['LOGGER']['NAME'])
		if 'LOGLEVEL' in self.config['LOGGER']:
			if self.config['LOGGER']['LOGLEVEL'] == 'DEBUG':
				self.logger.setLevel(logging.DEBUG)
			elif self.config['LOGGER']['LOGLEVEL'] == 'INFO' or self.config['LOGGER']['LOGLEVEL'] == '':
				self.logger.setLevel(logging.INFO)
		else:
			self.logger.setLevel(logging.INFO)

		handler = logging.handlers.SysLogHandler(address = '/dev/log')

		self.logger.addHandler(handler)
		
	def log(self, level, message):
		self.logQueue.put((level, self.name, message))
		
	def run(self):
		self.setup()
		self.log('DEBUG','Setup complete!')
		while True:
			log = self.logQueue.get()
			self.handleLog(log)
			
	def handleLog(self, log):
		level, src, message = log
		#print '[%s][%s][%s] %s' % (datetime.utcnow(), level, src, message)
		if level == 'DEBUG':
			self.logger.debug('[%s] %s' % (src, message))
		elif level == 'INFO':
			self.logger.info('[%s] %s' % (src, message))
		elif level == 'WARNING':
			self.logger.warning('[%s] %s' % (src, message))
		elif level == 'EXCEPTION':
			self.logger.critical('[%s] %s' % (src, message))
		
class ReportHandler(multiprocessing.Process):
	def __init__(self, reportQueue, logQueue, config):
		multiprocessing.Process.__init__(self)
		self.reportQueue = reportQueue
		self.logQueue = logQueue
		self.config = config
		
		self.gpsDataBuffer = []
		self.gpsDataBufferLock = threading.Lock()
		
	def setup(self):
		if config['UPLOADER']['UPLOAD_URL'][:5] == 'https' and config['UPLOADER']['SSL_VERIFY'] == False:
			self.log('WARNING','SSL certificate verification disabled! This is not recommended, please reconsider using a proper validation method!')
			requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

		threading.Timer(self.config['REPORTER']['UPLOADER_FREQ'], self.webSenderThread).start()
		threading.Timer(self.config['REPORTER']['REUPLOADER_FREQ'], self.reuploaderThread).start()
		
	def log(self, level, message):
		self.logQueue.put((level, self.name, message))
		
		
	def run(self):
		try:
			self.setup()
		except Exception as e:
			self.log('EXCEPTION','Error when setting up Reporter! Data: %s' % (e))
			return
		
		self.log('DEBUG','Setup complete!')
		
		while True:
			gpsdata = self.reportQueue.get()
			with self.gpsDataBufferLock:
				self.gpsDataBuffer.append(gpsdata)
	
	def webSenderThread(self):
		#### Rescheduling ourselves
		threading.Timer(self.config['REPORTER']['UPLOADER_FREQ'], self.webSenderThread).start()
		#### Checking if there is anything to send
		with self.gpsDataBufferLock:
			if len(self.gpsDataBuffer) == 0:
				self.log('WARNING','No GPS data to send! Is GPS configured right?')
				return
		#### Compressing raw GPS data with GZIP
		try:
			gzipdata = cStringIO.StringIO()
			with self.gpsDataBufferLock:
				with gzip.GzipFile(fileobj=gzipdata, mode="wb") as f:
					for gpsdata in self.gpsDataBuffer:
						f.write(gpsdata + '\r\n')
				
				self.gpsDataBuffer = []
				gzipdata.seek(0)
		except Exception as e:
			self.log('EXCEPTION', "Failed to compress GPS data! Data: %s" % (str(e)))
		#### Uploading compressed data
		try:
			self.log('INFO','Uploading GPS data to server...')
			uploader = UploadGPSData(self.config)
			uploader.upload(gzipdata.getvalue())
		except Exception as e:
			self.log('EXCEPTION', "Error while uploading data to server! Error data: %s" % (str(e)))
			try:
				with open(os.path.join(self.config['REPORTER']['FAILED_UPLOAD_DIR'],'gpsdata_%s.gzip' % (datetime.utcnow().strftime("%Y%m%d-%H%M%S"))),'wb') as f:
					gzipdata.seek(0)
					shutil.copyfileobj(gzipdata,f)
			except Exception as e:
				self.log('CRITICAL','Exception happened while saving GPS data to file system (which failed to upload to the server). Your GPS data is lost! Exception info: %s' % (e))
		
		#### Writing compressed data to disk when enabled
		if self.config['REPORTER']['WRITE_GPSDATA_FILE']:
			try:
				with open(os.path.join(self.config['REPORTER']['GPSDATA_DIR'],'gpsdata_%s.gzip' % (datetime.utcnow().strftime("%Y%m%d-%H%M%S"))),'wb') as f:
					gzipdata.seek(0)
					shutil.copyfileobj(gzipdata,f)
			except Exception as e:
				self.log('EXCEPTION', "Failed to write GPS data to disk! Data: %s" % (str(e)))
		
			
			
	def reuploaderThread(self):
		try:
			for filename in glob.glob(os.path.join(self.config['REPORTER']['FAILED_UPLOAD_DIR'], '*.gzip')):
				with open(filename, 'rb') as f:
					data = f.read()
					try:
						uploader = UploadGPSData(self.config)
						uploader.upload(data)
					except Exception as e:
						self.log('INFO', "Failed to upload temporary GPS data! Data: %s" % (str(e)))
						break
				
				os.remove(filename)
		except Exception as e:
			self.log('EXCEPTION', "Failed to read temporary GPS data! Data: %s" % (str(e)))
			
		threading.Timer(self.config['REPORTER']['REUPLOADER_FREQ'], self.reuploaderThread).start()
			
			
		
class UploadGPSData():
	def __init__(self, config):
		self.url = config['UPLOADER']['UPLOAD_URL'] + config['UPLOADER']['GPSTRACKER_UPLOAD_API'] +config['UPLOADER']['CLIENT_NAME']
		self.clientCert = config['UPLOADER']['TRACKER_CERT_FILE']
		self.clientKey = config['UPLOADER']['TRACKER_KEY_FILE']
		self.timeout = config['UPLOADER']['TIMEOUT']
		
	def upload(self, data):
		#TOCTOU in file existence check, but who cares?

		if self.url[:5].lower() != 'https' or self.clientCert == '' or self.clientKey == '' or not os.path.isfile(self.clientCert) or not os.path.isfile(self.clientKey):
			res = requests.post(
					url=self.url,
                    data=data,
                    headers={'Content-Type': 'application/octet-stream'},
					timeout=self.timeout)
		else:
			res = requests.post(
					url=self.url,
                    data=data,
                    headers={'Content-Type': 'application/octet-stream'},
					timeout=self.timeout,
					cert=(self.clientCert, self.clientKey), verify=config['UPLOADER']['SSL_VERIFY'])
			
		if res.status_code != requests.codes.ok:
			raise Exception("Server responsed with error! Code: %s" % (res.status_code,) )
		
		return
		
		
		
		
		
class GPSTracker():
	def __init__(self, config):
		self.reportQueue = multiprocessing.Queue()
		self.logQueue = multiprocessing.Queue()
		self.config = config
		self.name = 'GPSTracker'

	def log(self, level, message):
		self.logQueue.put((level, self.name, message))
		
	def setup(self):
		self.logger = Logger(self.logQueue, self.config)
		self.logger.daemon = True
		self.logger.start()
		
		self.poller = GPSPoller(self.reportQueue, self.logQueue, self.config)
		self.poller.daemon = True
		self.poller.start()
		
		self.reporter = ReportHandler(self.reportQueue, self.logQueue, self.config)
		self.reporter.daemon = True
		self.reporter.start()
	
	def bootstrap(self):
		data = json.dumps({'bootstrap_code': self.config['BOOTSTRAP']['BOOTSTRAP_CODE'], 'email': self.config['BOOTSTRAP']['BOOTSTRAP_EMAIL']})
		
		res = ''
		while True:
			self.log('DEBUG', "Trying to bootstrap tracker")
			try:
				res = requests.put(
							url=self.config['BOOTSTRAP']['BOOTSTRAP_URL'],
							data=data,
							headers={'Content-Type': 'application/json'},
							timeout=10,
							verify=self.config['UPLOADER']['SSL_VERIFY'])
				
				if res.status_code != requests.codes.ok:
					raise Exception("Server responsed with error! Code: %s" % (res.status_code,) )
				
				break
							
			except Exception as e:
				print "Failed to bootstrap tracker! Error: " + str(e)
				time.sleep(5)
				continue
				
		rj = json.loads(res.text)
		cert = rj['data']['cert']
		key = rj['data']['key']
		
		with open(self.config['TRACKER_CERT_FILE'],'wb') as f:
			f.write(cert)
			
		with open(self.config['TRACKER_KEY_FILE'],'wb') as f:
			f.write(key)
			
		
		self.log('INFO', "Bootstrap completed!")
	
	def run(self):
		self.clientCert = config['UPLOADER']['TRACKER_CERT_FILE']
		self.clientKey = config['UPLOADER']['TRACKER_KEY_FILE']
		
		
		if self.clientCert == '' or self.clientKey == '' or not os.path.isfile(self.clientCert) or not os.path.isfile(self.clientKey):
			if self.config['BOOTSTRAP']['BOOTSTRAP_CODE'] != '' and self.config['BOOTSTRAP']['BOOTSTRAP_EMAIL'] != '':
				self.bootstrap()
			else:
				self.log('CRITICAL','Missing client certificate and bootstrap data! Cant confinue, terminating!')
				return
		
		self.setup()
		while True:
			time.sleep(10)

			
			
if __name__ == '__main__':
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument("-v", "--verbose", help="Increase output verbosity", action="store_true")
	parser.add_argument("-c", "--config", help="Config file", default = '')
	parser.add_argument("-u", type = int, help= 'Upload fequency', default = 60)
	parser.add_argument("-g", help= 'Directory to keep GPS data in', default = './')
	parser.add_argument("-w", help= 'Keep local copy of GPS data', action="store_true")
	parser.add_argument("-f", help= 'Directory to store failed uploads', default = './failed/')
	parser.add_argument("-r", type = int, help= 'Reupload  retry frequency', default = 60)
	parser.add_argument("--upload-url",  help= 'GPSTracker web service URL', default = 'http://127.0.0.1/')
	parser.add_argument("--tracker-cert", help= 'Client cert file for upload SSL auth', default = './certs/client.pem')
	parser.add_argument("--tracker-key",  help= 'Client key file for upload SSL auth', default = './certs/client.key')
	parser.add_argument("-t", "--timeout", type = int, help= 'Data file upload timeout', default = 10)
	
	args = parser.parse_args()
	if args.config != '':
		with open(args.config, 'rb') as f:
			config = json.loads(f.read())
	
	else:
		config = {}
		config['REPORTER'] = {}
		config['UPLOADER'] = {}
		config['LOGGER'] = {}
		config['REPORTER']['UPLOADER_FREQ'] = args.u
		config['REPORTER']['GPSDATA_DIR']   = args.g
		config['REPORTER']['WRITE_GPSDATA_FILE'] = args.w
		config['REPORTER']['FAILED_UPLOAD_DIR'] = args.f
		config['REPORTER']['REUPLOADER_FREQ'] = args.r
		config['UPLOADER']['UPLOAD_URL'] = args.upload_url
		config['UPLOADER']['TRACKER_CERT_FILE'] = args.tracker_cert
		config['UPLOADER']['TRACKER_KEY_FILE']  = args.tracker_key
		config['UPLOADER']['TIMEOUT']     = args.timeout
		config['LOGGER']['NAME'] = 'GPSTrackerLogger'
		config['LOGGER']['LOGLEVEL'] = 'INFO'
		if args.verbose:
			config['LOGGER']['LOGLEVEL'] = 'DEBUG' 
		
	
	gpst = GPSTracker(config = config)
	gpst.run()
	

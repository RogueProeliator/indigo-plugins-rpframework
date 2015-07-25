#! /usr/bin/env python
# -*- coding: utf-8 -*-
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkRESTfulDevice by RogueProeliator <rp@rogueproeliator.com>
# 	This class is a concrete implementation of the RPFrameworkDevice as a device which
#	communicates via a REST style HTTP connection.
#	
#	Version 1.0.0 [10-18-2013]:
#		Initial release of the device framework
#	Version 1.0.5 [1-10-2014]:
#		Added GET operation command processing to the PUT command processing
#		Added status polling (as found in the Telnet device) to the RESTFul device
#		Added better reading of GET operation values (was read twice before)
#	Version 1.0.7:
#		Added short error message w/ trace only if debug is on for GET/PUT/SOAP
#		Added support for device database
#		Added overridable error handling function
#	Version 1.0.8 [5/2014]:
#		Removed update check as it is now at the plugin level
#	Version 1.0.10:
#		Added the DOWNLOAD_FILE command to save a file to disc from network (HTTP)
#	Version 1.0.12:
#		Added a shortened wait period after a command queue has recently emptied
#	Version 1.0.14:
#		Added custom header overridable function
#		Added JSON command
#		Changed handleDeviceResponse to get 3 arguments (reponse obj, text, command)
#		Fixed bug with the download file command when no authentication is enabled
#	Version 1.0.15:
#		Fixed bug with download file when issue occurs (null reference exception)
#
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////

#/////////////////////////////////////////////////////////////////////////////////////////
# Python imports
#/////////////////////////////////////////////////////////////////////////////////////////
import functools
import httplib
import indigo
import Queue
import os
import re
import string
import sys
import threading
import telnetlib
import time
import urllib
import urllib2
from urlparse import urlparse

import RPFrameworkPlugin
import RPFrameworkCommand
import RPFrameworkDevice
import RPFrameworkNetworkingWOL


#/////////////////////////////////////////////////////////////////////////////////////////
# Constants and configuration variables
#/////////////////////////////////////////////////////////////////////////////////////////
CMD_RESTFUL_PUT = "RESTFUL_PUT"
CMD_RESTFUL_GET = "RESTFUL_GET"
CMD_SOAP_REQUEST = "SOAP_REQUEST"
CMD_JSON_REQUEST = "JSON_REQUEST"
CMD_DOWNLOADFILE = "DOWNLOAD_FILE"

GUI_CONFIG_RESTFULSTATUSPOLL_INTERVALPROPERTY = "updateStatusPollerIntervalProperty"
GUI_CONFIG_RESTFULSTATUSPOLL_ACTIONID = "updateStatusPollerActionId"
GUI_CONFIG_RESTFULSTATUSPOLL_STARTUPDELAY = "updateStatusPollerStartupDelay"

GUI_CONFIG_RESTFULDEV_EMPTYQUEUE_SPEEDUPCYCLES = "emptyQueueReducedWaitCycles"


#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkRESTfulDevice
#	This class is a concrete implementation of the RPFrameworkDevice as a device which
#	communicates via a REST style HTTP connection.
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
class RPFrameworkRESTfulDevice(RPFrameworkDevice.RPFrameworkDevice):
	
	#/////////////////////////////////////////////////////////////////////////////////////
	# Class construction and destruction methods
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor called once upon plugin class receiving a command to start device
	# communication. Defers to the base class for processing but initializes params
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, plugin, device):
		super(RPFrameworkRESTfulDevice, self).__init__(plugin, device)
		
		
	#/////////////////////////////////////////////////////////////////////////////////////
	# Processing and command functions
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine is designed to run in a concurrent thread and will continuously monitor
	# the commands queue for work to do.
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def concurrentCommandProcessingThread(self, commandQueue):
		try:
			self.hostPlugin.logDebugMessage("Concurrent Processing Thread started for device " + str(self.indigoDevice.id), RPFrameworkPlugin.DEBUGLEVEL_MED)
		
			# obtain the IP or host address that will be used in connecting to the
			# RESTful service via a function call to allow overrides
			deviceHTTPAddress = self.getRESTfulDeviceAddress()
			if deviceHTTPAddress is None:
				indigo.server.log("No IP address specified for device " + str(self.indigoDevice.id) + "; ending command processing thread.", isError=True)
				return
			
			# retrieve any configuration information that may have been setup in the
			# plugin configuration and/or device configuration
			updateStatusPollerPropertyName = self.hostPlugin.getGUIConfigValue(self.indigoDevice.deviceTypeId, GUI_CONFIG_RESTFULSTATUSPOLL_INTERVALPROPERTY, "updateInterval")
			updateStatusPollerInterval = int(self.indigoDevice.pluginProps.get(updateStatusPollerPropertyName, "90"))
			updateStatusPollerNextRun = None
			updateStatusPollerActionId = self.hostPlugin.getGUIConfigValue(self.indigoDevice.deviceTypeId, GUI_CONFIG_RESTFULSTATUSPOLL_ACTIONID, "")
			emptyQueueReducedWaitCycles = int(self.hostPlugin.getGUIConfigValue(self.indigoDevice.deviceTypeId, GUI_CONFIG_RESTFULDEV_EMPTYQUEUE_SPEEDUPCYCLES, "80"))
			
			# spin up the database connection, if this plugin supports databases
			self.dbConn = self.hostPlugin.openDatabaseConnection(self.indigoDevice.deviceTypeId)
			
			# begin the infinite loop which will run as long as the queue contains commands
			# and we have not received an explicit shutdown request
			continueProcessingCommands = True
			lastQueuedCommandCompleted = 0
			while continueProcessingCommands == True:
				# process pending commands now...
				while not commandQueue.empty():
					lenQueue = commandQueue.qsize()
					self.hostPlugin.logDebugMessage("Command queue has " + str(lenQueue) + " command(s) waiting", RPFrameworkPlugin.DEBUGLEVEL_HIGH)
					
					# the command name will identify what action should be taken... we will handle the known
					# commands and dispatch out to the device implementation, if necessary, to handle unknown
					# commands
					command = commandQueue.get()
					if command.commandName == RPFrameworkCommand.CMD_INITIALIZE_CONNECTION:
						# specialized command to instanciate the concurrent thread
						# safely ignore this... just used to spin up the thread
						self.hostPlugin.logDebugMessage("Create connection command de-queued", RPFrameworkPlugin.DEBUGLEVEL_MED)
						
						# if the device supports polling for status, it may be initiated here now; however, we should implement a pause to ensure that
						# devices are created properly (RESTFul devices may respond too fast since no connection need be established)
						statusUpdateStartupDelay = float(self.hostPlugin.getGUIConfigValue(self.indigoDevice.deviceTypeId, GUI_CONFIG_RESTFULSTATUSPOLL_STARTUPDELAY, "3"))
						if statusUpdateStartupDelay > 0.0:
							commandQueue.put(RPFrameworkCommand.RPFrameworkCommand(RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload=str(statusUpdateStartupDelay)))
						commandQueue.put(RPFrameworkCommand.RPFrameworkCommand(RPFrameworkCommand.CMD_UPDATE_DEVICE_STATUS_FULL, parentAction=updateStatusPollerActionId))
						
					elif command.commandName == RPFrameworkCommand.CMD_TERMINATE_PROCESSING_THREAD:
						# a specialized command designed to stop the processing thread indigo
						# the event of a shutdown						
						continueProcessingCommands = False
						
					elif command.commandName == RPFrameworkCommand.CMD_PAUSE_PROCESSING:
						# the amount of time to sleep should be a float found in the
						# payload of the command
						try:
							pauseTime = float(command.commandPayload)
							self.hostPlugin.logDebugMessage("Initiating sleep of " + str(pauseTime) + " seconds from command.", RPFrameworkPlugin.DEBUGLEVEL_MED)
							time.sleep(pauseTime)
						except:
							indigo.server.log("Invalid pause time requested", isError=True)
							
					elif command.commandName == RPFrameworkCommand.CMD_UPDATE_DEVICE_STATUS_FULL:
						# this command instructs the plugin to update the full status of the device (all statuses
						# that may be read from the device should be read)
						if updateStatusPollerActionId != "":
							self.hostPlugin.logDebugMessage("Executing full status update request...", RPFrameworkPlugin.DEBUGLEVEL_MED)
							self.hostPlugin.executeAction(None, indigoActionId=updateStatusPollerActionId, indigoDeviceId=self.indigoDevice.id, paramValues=None)
							updateStatusPollerNextRun = time.time() + updateStatusPollerInterval
						else:
							self.hostPlugin.logDebugMessage("Ignoring status update request, no action specified to update device status", RPFrameworkPlugin.DEBUGLEVEL_HIGH)
							
					elif command.commandName == RPFrameworkCommand.CMD_NETWORKING_WOL_REQUEST:
						# this is a request to send a Wake-On-LAN request to a network-enabled device
						# the command payload should be the MAC address of the device to wake up
						try:
							RPFrameworkNetworkingWOL.sendWakeOnLAN(command.commandPayload)
						except:
							self.hostPlugin.exceptionLog()
						
					elif command.commandName == CMD_RESTFUL_PUT or command.commandName == CMD_RESTFUL_GET:
						try:
							# this is a put operation... create an HTTP GET or POST operation to be sent to
							# the device
							requestHttpVerb = "GET"
							if command.commandName == CMD_RESTFUL_PUT:
								requestHttpVerb = "POST"
							self.hostPlugin.logDebugMessage("Processing " + requestHttpVerb + " operation: " + command.commandPayload, RPFrameworkPlugin.DEBUGLEVEL_MED)
			
							conn = httplib.HTTPConnection(deviceHTTPAddress[0], int(deviceHTTPAddress[1]))
							conn.connect()
							conn.putrequest(requestHttpVerb, command.commandPayload)
							self.addCustomHTTPHeaders(conn)
							conn.endheaders()
			
							responseToREST = conn.getresponse()
							responseToRESTText = responseToREST.read()
							self.hostPlugin.logDebugMessage("Command Response: [" + str(responseToREST.status) + "] " + responseToRESTText, RPFrameworkPlugin.DEBUGLEVEL_HIGH)
			
							conn.close()						
							self.hostPlugin.logDebugMessage(command.commandName + " command completed.", RPFrameworkPlugin.DEBUGLEVEL_HIGH)
							
							# allow the framework to handle the response...
							self.handleDeviceResponse(responseToREST, responseToRESTText, command)
							
						except Exception, e:
							self.handleRESTfulError(command, e)
							if self.hostPlugin.debug == True:
								self.hostPlugin.exceptionLog()
						
					elif command.commandName == CMD_SOAP_REQUEST or command.commandName == CMD_JSON_REQUEST:
						try:
							# this is to post a SOAP request to a web service... this will be similar to a restful put request
							# but will contain a body payload
							self.hostPlugin.logDebugMessage("Received SOAP/JSON command request: " + command.commandPayload, RPFrameworkPlugin.DEBUGLEVEL_HIGH)
							soapPayloadParser = re.compile("^\s*([^\n]+)\n\s*([^\n]+)\n(.*)$", re.DOTALL)
							soapPayloadData = soapPayloadParser.match(command.commandPayload)
							soapPath = soapPayloadData.group(1).strip()
							soapAction = soapPayloadData.group(2).strip()
							soapBody = soapPayloadData.group(3).strip()
							self.hostPlugin.logDebugMessage("Processing SOAP/JSON operation to " + soapPath, RPFrameworkPlugin.DEBUGLEVEL_MED)

							conn = httplib.HTTPConnection(deviceHTTPAddress[0], int(deviceHTTPAddress[1]))
							conn.connect()
						
							conn.putrequest('POST', soapPath)
							if command.commandName == CMD_SOAP_REQUEST:
								conn.putheader("Content-type", "text/xml; charset=\"UTF-8\"")
								conn.putheader("SOAPAction", "\"" + soapAction + "\"")
							else:
								conn.putheader("Content-type", "application/json")
							self.addCustomHTTPHeaders(conn)
							conn.putheader("Content-Length", "%d" % len(soapBody))
							conn.endheaders()
						
							conn.send(soapBody)
							self.hostPlugin.logDebugMessage("Sending SOAP/JSON request:\n" + soapBody, RPFrameworkPlugin.DEBUGLEVEL_HIGH)
						
							soapResponse = conn.getresponse()
							soapResponseText = soapResponse.read()
							self.hostPlugin.logDebugMessage("Command Response: [" + str(soapResponse.status) + "] " + soapResponseText, RPFrameworkPlugin.DEBUGLEVEL_HIGH)
			
							conn.close()						
							self.hostPlugin.logDebugMessage(command.commandName + " command completed.", RPFrameworkPlugin.DEBUGLEVEL_HIGH)
							
							# allow the framework to handle the response...
							self.handleDeviceResponse(soapResponse, soapResponseText, command)
						except Exception, e:
							self.handleRESTfulError(command, e)
							if self.hostPlugin.debug == True:
								self.hostPlugin.exceptionLog()
					
					elif command.commandName == CMD_DOWNLOADFILE:
						try:
							# this is a request to download a file from the network to the local computer; the command
							# payload must include the complete URL and the file to save
							downloadSource = command.commandPayload[0]
							saveLocation = command.commandPayload[1]
							parsedUrl = urlparse(downloadSource)
							authenticationType = command.commandPayload[2]
							username = command.commandPayload[3]
							password = command.commandPayload[4]
							
							self.hostPlugin.logDebugMessage("Processing SOAP operation to download " + downloadSource + " to " + saveLocation, RPFrameworkPlugin.DEBUGLEVEL_MED)
							authHandler = None
							if authenticationType == "Basic" and username != "" and password != "":
								passwordManager = urllib2.HTTPPasswordMgrWithDefaultRealm()
								passwordManager.add_password(None, parsedUrl.netloc, username, password)
								authHandler = urllib2.HTTPBasicAuthHandler(passwordManager)
								opener = urllib2.build_opener(authHandler)
							else:
								opener = urllib2.build_opener()
							
							# process the download
							f = opener.open(downloadSource)
							try:
								localFile = open(saveLocation, "wb")
								localFile.write(f.read())
							finally:
								if not localFile is None:
									localFile.close()					
							f.close()
							
							# allow the plugin to handle the response, in this case just say "success" since
							# we don't have a real return
							self.handleDeviceResponse(None, "CMD_DOWNLOADFILE: Success", command)
							
						except Exception, e:
							self.handleRESTfulError(command, e)
							if self.hostPlugin.debug == True:
								self.hostPlugin.exceptionLog()
						
					else:
						# this is an unknown command; dispatch it to another routine which is
						# able to handle the commands (to be overridden for individual devices)
						self.handleUnmanagedCommandInQueue(deviceHTTPAddress, command)
					
					# if the command has a pause defined for after it is completed then we
					# should execute that pause now
					if command.postCommandPause > 0.0 and continueProcessingCommands == True:
						self.hostPlugin.logDebugMessage("Post Command Pause: " + str(command.postCommandPause), RPFrameworkPlugin.DEBUGLEVEL_MED)
						time.sleep(command.postCommandPause)
					
					# complete the dequeuing of the command, allowing the next
					# command in queue to rise to the top
					commandQueue.task_done()
					lastQueuedCommandCompleted = emptyQueueReducedWaitCycles
				
				# when the queue is empty, pause a bit on each iteration
				if continueProcessingCommands == True:
					# if we have just completed a command recently, half the amount of
					# wait time, assuming that a subsequent command could be forthcoming
					if lastQueuedCommandCompleted > 0:
						time.sleep(self.emptyQueueProcessingThreadSleepTime/2)
						lastQueuedCommandCompleted = lastQueuedCommandCompleted - 1
					else:
						time.sleep(self.emptyQueueProcessingThreadSleepTime)
				
				# check to see if we need to issue an update...
				if updateStatusPollerNextRun is not None and time.time() > updateStatusPollerNextRun:
					commandQueue.put(RPFrameworkCommand.RPFrameworkCommand(RPFrameworkCommand.CMD_UPDATE_DEVICE_STATUS_FULL, parentAction=updateStatusPollerActionId))
				
		# handle any exceptions that are thrown during execution of the plugin... note that this
		# should terminate the thread, but it may get spun back up again
		except SystemExit:
			pass
		except Exception:
			self.hostPlugin.exceptionLog()
		except:
			self.hostPlugin.exceptionLog()
		finally:
			self.hostPlugin.logDebugMessage("Command thread ending processing", RPFrameworkPlugin.DEBUGLEVEL_LOW)
			self.hostPlugin.closeDatabaseConnection(self.dbConn)
		
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine should return the HTTP address that will be used to connect to the
	# RESTful device. It may connect via IP address or a host name
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def getRESTfulDeviceAddress(self):
		return None
	
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine should be overridden in individual device classes whenever they must
	# handle custom commands that are not already defined
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def handleUnmanagedCommandInQueue(self, deviceHTTPAddress, rpCommand):
		pass
		
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will be called prior to any network operation to allow the addition
	# of custom headers to the request (does not include file download)
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def addCustomHTTPHeaders(self, httpRequest):
		pass
		
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will process any response from the device following the list of
	# response objects defined for this device type. For telnet this will always be
	# a text string
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def handleDeviceResponse(self, responseObj, responseText, rpCommand):
		# loop through the list of response definitions defined in the (base) class
		# and determine if any match
		for rpResponse in self.hostPlugin.getDeviceResponseDefinitions(self.indigoDevice.deviceTypeId):
			if rpResponse.isResponseMatch(responseText, rpCommand, self, self.hostPlugin):
				self.hostPlugin.logDebugMessage("Found response match: " + rpResponse.responseId, RPFrameworkPlugin.DEBUGLEVEL_MED)
				rpResponse.executeEffects(responseText, rpCommand, self, self.hostPlugin)
	
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will handle an error as thrown by the REST call... it allows 
	# descendant classes to do their own processing
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-		
	def handleRESTfulError(self, rpCommand, err):
		if rpCommand.commandName == CMD_RESTFUL_PUT or rpCommand.commandName == CMD_RESTFUL_GET:
			indigo.server.log("An error occurred executing the GET/PUT request (Device: " + str(self.indigoDevice.id) + "): " + str(err), isError=True)
		else:
			indigo.server.log("An error occurred processing the SOAP/JSON POST request: (Device: " + str(self.indigoDevice.id) + "): " + str(err), isError=True)		
	
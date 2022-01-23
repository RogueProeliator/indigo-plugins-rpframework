#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2017, Perceptive Automation, LLC. All rights reserved.
# http://www.indigodomo.com

import errno
import json
import logging
import logging.handlers
import os
import re
import select
import string
import sys
import threading
import time
import traceback
import xml.etree.ElementTree as xmlTree
from xmljson import badgerfish as badgerfish

import readline		# readline import required for command history to work correctly
import functools
from code import InteractiveConsole

import serial
import indigo

################################################################################
kPluginConfigFilename = u"PluginConfig"		# + .xml or .json
kMenuItemsFilename = u"MenuItems"			# + .xml or .json
kDevicesFilename = u"Devices"				# + .xml or .json
kEventsFilename = u"Events"					# + .xml or .json
kActionsFilename = u"Actions"				# + .xml or .json

kPluginDebugMode_debugShell = 200	# Mirrored from CPlugin.h

################################################################################
################################################################################
# Logging additions
################################################################################
# For backwards compatibility, we need to define a NullHandler (it's defined
# in Python 2.7 but we still support 2.6
try:
	from logging import NullHandler
except ImportError:
	class NullHandler(logging.Handler):
		def emit(self, record):
			pass
	logging.NullHandler = NullHandler

################################################################################
# Adding a new THREADDEBUG level at 5 for more detailed debugging
################################################################################
# First, we add the level name and the actual level to the logging module
logging.addLevelName(5, "THREADDEBUG")
logging.THREADDEBUG = 5

# Next, we create our own version of the Logger class that adds a threaddebug
# method that parallel's debug, info, etc.
class IndigoLogger(logging.Logger):
	def threaddebug(self, msg, *args, **kwargs):
		if self.isEnabledFor(logging.THREADDEBUG):
			self._log(logging.THREADDEBUG, msg, args, **kwargs)

# We tell the logger module to use this Logger object as the one to create
# when logger.getLogger() is called
logging.setLoggerClass(IndigoLogger)

################################################################################
# Finally, we define a logging handler that emits log messages into the Indigo
# Event Log.
################################################################################
class IndigoLogHandler(logging.Handler, object):
	def __init__(self, displayName, level=logging.NOTSET):
		super(IndigoLogHandler, self).__init__(level)
		self.displayName = displayName

	def emit(self, record):
		# First, determine if it needs to be an Indigo error
		is_error = False
		if record.levelno in (logging.ERROR, logging.CRITICAL):
			is_error = True
		type_string = self.displayName
		# For any level besides INFO and ERROR (which Indigo handles), we append
		# the debug level (i.e. Critical, Warning, Debug, etc) to the type string
		if record.levelno not in (logging.INFO, logging.ERROR):
			type_string += u" %s" % record.levelname.title()
		# Then we write the message
		indigo.server.log(message=self.format(record), type=type_string, isError=is_error)

################################################################################
################################################################################
def _consoleThreadRun(plugin):
	plugin.pluginDisplayName
	ver_str = "Python %s\n" % (sys.version)
	ver_str += "Connected to Indigo Server v%s, api v%s (%s:%d)\n" % (indigo.server.version, indigo.server.apiVersion, indigo.server.address, indigo.server.portNum)
	ver_str += "Started Plugin %s v%s" % (plugin.pluginDisplayName, plugin.pluginVersion)

	try:
		globs = globals()
		globs["self"] = plugin
		shell = InteractiveConsole(globs)

		# Originally here we just called shell.interact(ver_str), but we need
		# a check inside the REPR to see if plugin.stopThread is set so we can
		# more gracefully shutdown the plugin if the user does CNTRL-C which
		# sends a SIGINT. Normally that would be translated by python into a
		# KeyboardInterrupt exception, but not for us since the IndigoPluginHost
		# already defined a signal override for SIGINT (see CAppCore::_CatchKernelSignal).
		#
		# The code below is very similar to shell.interact() except for the additional
		# plugin.stopThread conditional.
		#
		#	shell.interact(ver_str)
		#
		try:
			sys.ps1
		except AttributeError:
			sys.ps1 = ">>> "
		try:
			sys.ps2
		except AttributeError:
			sys.ps2 = "... "
		shell.write("%s\n" % str(ver_str))
		more = 0
		while 1:
			if more:
				prompt = sys.ps2
			else:
				prompt = sys.ps1
			try:
				line = shell.raw_input(prompt)
				if plugin.stopThread:			# Perceptive added conditional. (mmb)
					raise plugin.StopThread
				# Can be None if sys.stdin was redefined
				encoding = getattr(sys.stdin, "encoding", None)
				if encoding and not isinstance(line, unicode):
					line = line.decode(encoding)
			except EOFError:
				shell.write("\n")
				break
			else:
				more = shell.push(line)
			# Perceptive commented out. We want CNTRL-C to exit the plugin -- not just
			# reset the buffer. This code actually isn't executed because IndigoPluginHost
			# defines a signal override for SIGINT, but I want to comment it out to make
			# it clear we wouldn't want it executed even if that signal didn't exist. (mmb)
			# try:
			#	code above inside while loop
			# except KeyboardInterrupt:
			#	shell.write("\nKeyboardInterrupt\n")
			#	shell.resetbuffer()
			#	more = 0
	except Exception, e:
		# plugin.debugLog(u"console thread exception: %s" % unicode(e))
		pass
	finally:
		# plugin.debugLog(u"console thread exiting")
		plugin.stopPlugin(u"", False)

def startInteractiveConsole(plugin):
	consoleThread = threading.Thread(
		target=functools.partial(_consoleThreadRun, plugin)
	)
	consoleThread.setName("consoleThread")
	consoleThread.start()
	return consoleThread

################################################################################
validDeviceTypes = ["dimmer", "relay", "sensor", "speedcontrol", "thermostat", "sprinkler", "custom"]

fieldTypeTemplates = {
	# Key is node <Field> type attribute, value is template file name.
	u"serialport": u"_configUiField_serialPort.json"
}

################################################################################
################################################################################
# Class PluginBase, defined below, will be automatically inserted into the
# "indigo" namespace by the host process. Any classes, functions, variables,
# etc., defined outside the PluginBase class scope will NOT be inserted.
#
# Additionally, the variable activePlugin is installed into the indigo global
# namespace. It always points to the active plugin instance (subclass of
# indigo.PluginBase, defined by plugin.py).

################################################################################
################################################################################
class PluginBase(object):
	""" Base Indigo Plugin class that provides some default behaviors and utility functions. """
	############################################################################
	class InterfaceError(Exception):
		def __init__(self, value=None):
			super(PluginBase.InterfaceError, self).__init__(value)

	class InvalidParameter(Exception):
		def __init__(self, value=None):
			super(PluginBase.InvalidParameter, self).__init__(value)

	class StopThread(Exception):
		def __init__(self, value=None):
			super(PluginBase.StopThread, self).__init__(value)

	############################################################################
	menuItemsList = indigo.List()
	menuItemsDict = indigo.Dict()
	devicesTypeDict = indigo.Dict()
	eventsTypeDict = indigo.Dict()
	actionsTypeDict = indigo.Dict()

	########################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		##################
		indigo._initializeDebugger()	# For connecting to PyCharm debug server.

		##################
		# pluginPrefs is an Indigo dictionary object of all preferences which
		# are automatically loaded before we are initialized, and automatically
		# saved after shutdown().
		self.pluginId = pluginId
		self.pluginDisplayName = pluginDisplayName
		self.pluginVersion = pluginVersion
		self.pluginPrefs = pluginPrefs
		self.consoleThread = None

		self.deviceFactoryXml = None

		self.jsonStripTokenizer = None

		##################
		# Set up logging first (before parsing XML or anything else that might need to log).
		self._debug = False
		# Plugin (as in the plugin class) is the log namespace
		self.logger = logging.getLogger("Plugin")
		# We set the level to THREADDEBUG so everything gets to each handler - the handlers can then
		# filter messages at the levels they want
		self.logger.setLevel(logging.THREADDEBUG)
		self.indigo_log_handler = IndigoLogHandler(pluginDisplayName, logging.INFO)
		ifmt = logging.Formatter('%(message)s')
		self.indigo_log_handler.setFormatter(ifmt)
		# The Indigo handler gets set to INFO so only INFO or greater messages get logged (no debugging)
		self.indigo_log_handler.setLevel(logging.INFO)
		self.logger.addHandler(self.indigo_log_handler)

		log_dir = indigo.server.getLogsFolderPath(pluginId)
		log_dir_exists = os.path.isdir(log_dir)
		if not log_dir_exists:
			try:
				os.mkdir(log_dir)
				log_dir_exists = True
			except:
				indigo.server.log(u"unable to create plugin log directory - logging to the system console", isError=True)
				self.plugin_file_handler = logging.StreamHandler()
		if log_dir_exists:
			self.plugin_file_handler = logging.handlers.TimedRotatingFileHandler("%s/plugin.log" % log_dir, when='midnight', backupCount=5)

		pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t%(levelname)s\t%(name)s.%(funcName)s:\t%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
		self.plugin_file_handler.setFormatter(pfmt)
		# The file handler gets set to THREADDEBUG so everything gets logged there by default
		self.plugin_file_handler.setLevel(logging.THREADDEBUG)
		self.logger.addHandler(self.plugin_file_handler)

		##################
		# Create a pipe for efficient sleeping via select().
		self.stopThread = False
		self._stopThreadPipeIn, self._stopThreadPipeOut = os.pipe()

		##################
		# Parse the XML files and store the pieces we or other clients will need later.
		try:
			self._parseMenuItemsXML(kMenuItemsFilename)
			self._parseDevicesXML(kDevicesFilename)
			self._parseEventsXML(kEventsFilename)
			self._parseActionsXML(kActionsFilename)
		except Exception, e:
			# The parse methods are good about giving verbose information regarding XML syntax errors
			# in the exception, so just log the exception here:
			self.logger.error(unicode(e))
			# And then raise a StopThread exception, which will cause IPH to shutdown the plugin
			# and will *not* log the exception stack trace -- it wouldn't be useful for debugging XML
			# syntax errors.
			raise self.StopThread

		##################
		if indigo.host.debugMode == kPluginDebugMode_debugShell:
			self.consoleThread = startInteractiveConsole(self)

	@property
	def debug(self):
		if not hasattr(self, '_debug'):
			return False
		return self._debug

	@debug.setter
	def debug(self, value):
		self._debug = value
		#
		# Note this only sets the logging level to DEBUG for the indigo_log_handler
		# (used by IndigoServer). The plugin_file_handler (per plugin log files)
		# intentionally default to always showing debug logging. If needed this can
		# be overriden by the plugin directly calling:
		#
		#	self.plugin_file_handler.setLevel(logging.INFO)
		#
		if not hasattr(self, 'indigo_log_handler'):
			return
		if value:
			self.indigo_log_handler.setLevel(logging.DEBUG)
		else:
			self.indigo_log_handler.setLevel(logging.INFO)

	########################################
	@staticmethod
	def versStrToTuple(versStr):
		cleaned = versStr
		if cleaned.find("alpha") >= 0:
			cleaned = cleaned[:cleaned.find("alpha")]
		elif cleaned.find("beta") >= 0:
			cleaned = cleaned[:cleaned.find("beta")]
		elif cleaned.find("a") >= 0:
			cleaned = cleaned[:cleaned.find("a")]
		elif cleaned.find("b") >= 0:
			cleaned = cleaned[:cleaned.find("b")]
		cleaned = cleaned.strip()
		verslist = cleaned.split(".")
		while len(verslist) < 4:
			verslist.append(u'0')
		return tuple(map(int, verslist))

	@staticmethod
	def versGreaterThanOrEq(cmpVersStr, baseVersStr):
		return PluginBase.versStrToTuple(cmpVersStr) >= PluginBase.versStrToTuple(baseVersStr)

	@staticmethod
	def serverVersCompatWith(versStr):
		return PluginBase.versGreaterThanOrEq(indigo.server.version, versStr)

	########################################
	# Log methods for backwards compatibility. Should use the self.logger Python logger instead.
	########################################
	def debugLog(self, msg):
		if not hasattr(self, 'logger'):
			return
		self.logger.debug(msg)

	def errorLog(self, msg):
		if not hasattr(self, 'logger'):
			return
		self.logger.error(msg)

	def exceptionLog(self):
		if not hasattr(self, 'logger'):
			return
		try:
			self.logger.error(u"Error in plugin execution:\n\n" + traceback.format_exc(30))
		except:
			pass	# shouldn't ever throw, but don't raise if it does

	########################################
	def launchDebugger(self):
		break_on_launch = False		# This works, but needs to be a UI option AND I'm not sure it is a great idea
		if break_on_launch:			# since it breaks in here and not the developer's source file.
			indigo.debugger()

#	def startup(self):
#		self.logger.debug(u"startup called")

	def _postStartup(self):
		self._deviceEnumAndStartComm()
		self._triggerEnumAndStartProcessing()

	########################################
#	def shutdown(self):
#		self.logger.debug(u"shutdown called")

	def _preShutdown(self):
		self.stopConcurrentThread()
		self._triggerEnumAndStopProcessing()
		self._deviceEnumAndStopComm()
		if self.consoleThread is not None:
			if self.consoleThread.isAlive():
				self.logger.info(u"waiting for interactive console window to close")
				self.consoleThread.join()
			self.consoleThread = None

	########################################
	def prepareToSleep(self):
		self._triggerEnumAndStopProcessing()
		self._deviceEnumAndStopComm()

	########################################
	def wakeUp(self):
		self._deviceEnumAndStartComm()
		self._triggerEnumAndStartProcessing()

	########################################
	def _preRunConcurrentThread(self):
		# PyCharm debugger needs a settrace() call inside our RunConcurrentThread
		# thread for breakpoints to work correctly.
		indigo._initializeDebugger()

#	def runConcurrentThread(self):
#		try:
#			while True:
#				self.logger.debug(u"processing something...")
#				# Do your stuff here
#				self.Sleep(8)
#		except self.StopThread:
#			pass	# optionally catch the StopThread and do any needed cleanup

	########################################
	def stopConcurrentThread(self):
		self.stopThread = True
		os.write(self._stopThreadPipeOut, "*")

	########################################
	def stopPlugin(self, message="", isError=True):
		indigo.server.stopPlugin(message=message, isError=isError)

	########################################
	def sleep(self, seconds):
		if self.stopThread:
			raise self.StopThread
		if seconds <= 0.0:
			return

		curTime = time.time()
		stopTime = curTime + seconds
		while curTime < stopTime:
			try:
				select.select([self._stopThreadPipeIn], [], [], stopTime - curTime)
			except select.error, doh:
				# Select will throw "interrupted system call" EINTR if the process
				# receives a signal (IndigoServer can send them during kill requests).
				# Just ignore them (self.stopThread will be set on kill request) but
				# do raise up any other exceptions select() might throw.
				if doh[0] != errno.EINTR:
					raise
			if self.stopThread:
				raise self.StopThread
			curTime = time.time()

	########################################
	###################
	@staticmethod
	def _getChildElementsByTagName2(elem, tagName):
		return elem.findall("%s" % tagName)

	@staticmethod
	def _getChildSingleElementByTagName2(elem, tagName, required=True, default=None, filename=u"unknown"):
		children = elem.findall("%s" % tagName)
		if len(children) == 0:
			if required:
				raise ValueError(u"required XML element <%s> is missing from <%s> in file %s" % (tagName,elem.tag,filename))
			return default
		elif len(children) > 1:
			raise ValueError(u"found %d <%s> XML elements inside <%s> in file %s (should only be one)" % (len(children),tagName,elem.tag,filename))
		return children[0]

	@staticmethod
	def _getFileContents(filename):
		if not os.path.isfile(filename):
			return u""
		f = file(filename, 'r')
		data = f.read()
		f.close()
		return data

	@staticmethod
	def _getTemplateParentFolder():
		return indigo.host.resourcesFolderPath + '/templates/'

	@staticmethod
	def _getElementAttribute2(elem, attrName, required=True, default=None, errorIfNotAscii=True, filename=u"unknown"):
		attrStr = elem.get(attrName)
		if attrStr is None or len(attrStr) == 0:
			if required:
				raise ValueError(u"required XML attribute '%s' is missing or empty in <%s> of file %s" % (attrName,elem.tag,filename))
			return default
		elif errorIfNotAscii and attrStr[0] not in string.ascii_letters:
			raise ValueError(u"XML attribute '%s' in file %s has a value that starts with invalid characters: '%s' (should begin with A-Z or a-z):\n%s" % (attrName,filename,attrStr,xmlTree.tostring(elem, method="xml")))
		return attrStr

	@staticmethod
	def _getElementValueByTagName2(elem, tagName, required=True, default=None, filename=u"unknown"):
		child = PluginBase._getChildSingleElementByTagName2(elem, tagName, required=required, default=None, filename=filename)
		if child is None:
			return default
		value = child.text
		if value is None or len(value) == 0:
			if required:
				raise ValueError(u"required XML element <%s> inside <%s> of file %s is empty" % (tagName,elem.tag,filename))
			return default
		return value

	###################
	def _parseMenuItemsXML(self, filename):
		if not self._xmlOrJsonFileExist(filename):
			return
		(menuItemsTree, filename) = self._xmlOrJsonParse(filename)
		if menuItemsTree.tag != "MenuItems":
			raise LookupError(u"Incorrect number of <MenuItems> elements found in file %s" % (filename))

		menuItems = self._getChildElementsByTagName2(menuItemsTree, u"MenuItem")
		for menu in menuItems:
			serverVers = self._getElementAttribute2(menu, u"_minServerVers", required=False, errorIfNotAscii=False, filename=filename)
			if serverVers is not None and not PluginBase.serverVersCompatWith(serverVers):
				continue	# This version of Indigo Server isn't compatible with this object (skip it)

			menuDict = indigo.Dict()
			menuId = self._getElementAttribute2(menu, u"id", filename=filename)
			if menuId in self.menuItemsDict:
				raise LookupError(u"Duplicate menu id (%s) found in file %s" % (menuId, filename))

			menuDict[u"Id"] = menuId
			menuDict[u"Name"] = self._getElementValueByTagName2(menu, u"Name", False, filename=filename)

			if "Name" in menuDict:
				menuDict[u"ButtonTitle"] = self._getElementValueByTagName2(menu, u"ButtonTitle", False, filename=filename)

				# Plugin should specify at least a CallbackMethod or ConfigUIRawXml (possibly both)
				menuDict[u"CallbackMethod"] = self._getElementValueByTagName2(menu, u"CallbackMethod", False, filename=filename)
				configUi = self._getChildSingleElementByTagName2(menu, u"ConfigUI", required=False, filename=filename)
				if configUi is not None:
					menuDict[u"ConfigUIRawXml"] = self._parseConfigUINode(configUi, filename=filename)
				elif not "CallbackMethod" in menuDict:
					raise ValueError(u"<MenuItem> elements must contain either a <CallbackMethod> and/or a <ConfigUI> element")

			self.menuItemsList.append(menuDict)
			self.menuItemsDict[menuId] = menuDict

	###################
	def _swapTemplatedField(self, configUI, refnode, refId, templateFilename, fileInHostBundle):
		(templateTree, filename) = self._xmlOrJsonParse(templateFilename, fileInHostBundle=fileInHostBundle, templateSwapFieldId=refId)
		if templateTree.tag != "Template":
			raise LookupError(u"XML template file %s must have one root level <Template> node" % (filename))

		importFieldList = self._getChildElementsByTagName2(templateTree, u"Field")
		insertIndex = list(configUI).index(refnode)
		for importField in importFieldList:
			configUI.insert(insertIndex, importField)
			insertIndex += 1

		configUI.remove(refnode)
		return configUI

	def _parseConfigUINode(self, configUI, filename=u"unknown", returnXml=True):
		# Parse all of the config Field nodes looking for any template
		# substitution that needs to occur. For example, <Field> nodes of
		# type="serialport" are substituted with the XML from file
		# _configUiField_serialPort.xml to provide a more complete multi-
		# field control that allows local serial ports and IP based
		# serial connections.
		fieldList = self._getChildElementsByTagName2(configUI, u"Field")
		for refnode in fieldList:
			typeVal = self._getElementAttribute2(refnode, u"type", filename=filename).lower()
			if typeVal in fieldTypeTemplates:
				templatename = fieldTypeTemplates[typeVal]
				refId = self._getElementAttribute2(refnode, u"id", False, filename=templatename)
				self._swapTemplatedField(configUI, refnode, refId, templatename, True)

		fieldList = self._getChildElementsByTagName2(configUI, u"Template")
		for refnode in fieldList:
			templatename = self._getElementAttribute2(refnode, u"file", filename=filename)
			if templatename:
				refId = self._getElementAttribute2(refnode, u"id", False, filename=templatename)
				self._swapTemplatedField(configUI, refnode, refId, templatename, False)

		# self.logger.debug(u"configUI:\n" + xmlTree.tostring(configUI, encoding="UTF-8", method="xml") + "\n")
		if returnXml:
			return xmlTree.tostring(configUI, encoding="UTF-8", method="xml")
		else:
			return configUI

	########################################
	def _stripJsonComments(self, input, strip_space=False):
		def replacer(match):
			ss = match.group(0)
			return " " if ss.startswith('/') else ss

		if self.jsonStripTokenizer is None:
			self.jsonStripTokenizer = re.compile(
				r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
				re.DOTALL | re.MULTILINE
	    	)
		return re.sub(self.jsonStripTokenizer, replacer, input)

	def _xmlOrJsonFileExist(self, basename):
		return os.path.isfile(basename + ".xml") or os.path.isfile(basename + ".json")

	def _xmlOrJsonParse(self, basename, fileInHostBundle=False, templateSwapFieldId=None):
		# .json file version takes priority, but if it isn't found we'll try for the .xml version.
		# Note if files aren't found then an empty xml ElementTree element is returned.
		parentFolder = "./"
		if fileInHostBundle:
			parentFolder = self._getTemplateParentFolder()

		if basename.endswith('.json'):
			isXml = False
			filename = basename
		elif basename.endswith('.xml'):
			isXml = True
			filename = basename
		else:
			filename = basename + ".json"
			if os.path.isfile(parentFolder + filename):
				isXml = False
			else:
				isXml = True
				filename = basename + ".xml"

		try:
			elemTree = None
			if os.path.isfile(parentFolder + filename):
				rawContents = self._getFileContents(parentFolder + filename)
				if len(rawContents) > 0:
					if templateSwapFieldId is not None:
						rawContents = rawContents.replace("_FIELDID", templateSwapFieldId)

					if isXml:
						elemTree = xmlTree.XML(rawContents)
					else:
						jsonTree = json.loads(self._stripJsonComments(rawContents))
						elemTreeList = badgerfish.etree(jsonTree)
						if len(elemTreeList) > 0:
							elemTree = elemTreeList[0]

						# Useful for debugging:
						#
						# from xml.dom import minidom
						# prettyXml = minidom.parseString(xmlTree.tostring(elemTree, encoding="UTF-8", method="xml")).toprettyxml()
						# self.logger.debug(u"json converted input:\n%s" % (prettyXml))

			if elemTree is None:
				elemTree = xmlTree.Element("Empty")
			return (elemTree, filename)
		except Exception, e:
			self.logger.error(u"%s has an error: %s" % (filename, unicode(e)))
			raise LookupError(u"%s is malformed" % (filename))

	# This isn't called from anywhere in here, but is just a handy utility function
	# that developers can call from their plugin's interfactive shell like this:
	#
	#	self.convertXmlFileToJson("Actions")
	#	self.convertXmlFileToJson("Devices")
	#	self.convertXmlFileToJson("Events")
	#	self.convertXmlFileToJson("MenuItems")
	#	self.convertXmlFileToJson("PluginConfig")
	#
	# Which will result in the .json versions of the XML files all being saved.
	#
	def convertXmlFileToJson(self, basename):
		if basename.endswith('.xml'):
			basename = basename[:-4]
		if not self._xmlOrJsonFileExist(basename):
			print("File not found: %s" % (basename))
			return
		(xmlElemTree, filename) = self._xmlOrJsonParse(basename)

		# We only read (and thus write here) JSON using the badgerfish convention,
		# which states that attributes are prefixed with "@" into properties and
		# the text content of elements is stored into a property named "$".
		pyElemTree = badgerfish.data(xmlElemTree)
		jsonRaw = json.dumps(pyElemTree, indent=4)
		jsonFilename = basename + ".json"

		f = file(jsonFilename, 'w')
		f.write(jsonRaw)
		f.close()
		print("File converted and saved to: %s" % (jsonFilename))
		print("Note for the .json version of the file to be used the .xml version must be renamed or deleted.")

	###################
	def _getDeviceStateDictForType(self, type, stateId, triggerLabel, controlPageLabel, disabled=False):
		stateDict = indigo.Dict()
		stateDict[u"Type"] = int(type)
		stateDict[u"Key"] = stateId
		stateDict[u"Disabled"] = disabled
		stateDict[u"TriggerLabel"] = triggerLabel
		stateDict[u"StateLabel"] = controlPageLabel
		return stateDict

	def getDeviceStateDictForSeparator(self, stateId):
		return self._getDeviceStateDictForType(indigo.kTriggerKeyType.Label, stateId, u"_Separator", u"_Separator", True)

	def getDeviceStateDictForSeperator(self, stateId):
		return self.getDeviceStateDictForSeparator(stateId)

	def getDeviceStateDictForNumberType(self, stateId, triggerLabel, controlPageLabel, disabled=False):
		return self._getDeviceStateDictForType(indigo.kTriggerKeyType.Number, stateId, triggerLabel, controlPageLabel, disabled)

	def getDeviceStateDictForStringType(self, stateId, triggerLabel, controlPageLabel, disabled=False):
		return self._getDeviceStateDictForType(indigo.kTriggerKeyType.String, stateId, triggerLabel, controlPageLabel, disabled)

	def getDeviceStateDictForEnumType(self, stateId, triggerLabel, controlPageLabel, disabled=False):
		return self._getDeviceStateDictForType(indigo.kTriggerKeyType.Enumeration, stateId, triggerLabel, controlPageLabel, disabled)

	def getDeviceStateDictForBoolOnOffType(self, stateId, triggerLabel, controlPageLabel, disabled=False):
		stateDict = self._getDeviceStateDictForType(indigo.kTriggerKeyType.BoolOnOff, stateId, triggerLabel, controlPageLabel, disabled)
		stateDict[u"StateLabel"] = stateDict[u"StateLabel"] + u" (on or off)"
		return stateDict

	def getDeviceStateDictForBoolYesNoType(self, stateId, triggerLabel, controlPageLabel, disabled=False):
		stateDict = self._getDeviceStateDictForType(indigo.kTriggerKeyType.BoolYesNo, stateId, triggerLabel, controlPageLabel, disabled)
		stateDict[u"StateLabel"] = stateDict[u"StateLabel"] + u" (yes or no)"
		return stateDict

	def getDeviceStateDictForBoolOneZeroType(self, stateId, triggerLabel, controlPageLabel, disabled=False):
		stateDict = self._getDeviceStateDictForType(indigo.kTriggerKeyType.BoolOneZero, stateId, triggerLabel, controlPageLabel, disabled)
		stateDict[u"StateLabel"] = stateDict[u"StateLabel"] + u" (1 or 0)"
		return stateDict

	def getDeviceStateDictForBoolTrueFalseType(self, stateId, triggerLabel, controlPageLabel, disabled=False):
		stateDict = self._getDeviceStateDictForType(indigo.kTriggerKeyType.BoolTrueFalse, stateId, triggerLabel, controlPageLabel, disabled)
		stateDict[u"StateLabel"] = stateDict[u"StateLabel"] + u" (true or false)"
		return stateDict

	def _parseDevicesXML(self, filename):
		if not self._xmlOrJsonFileExist(filename):
			return
		(devicesTree, filename) = self._xmlOrJsonParse(filename)
		if devicesTree.tag != "Devices":
			raise LookupError(u"Incorrect number of <Devices> elements found in file %s" % (filename))

		# Look for a DeviceFactory element - that will be used to create devices
		# rather than creating them directly using the <Device> XML. This allows
		# a plugin to discover device types rather than forcing the user to select
		# the type up-front (like how INSTEON devices are added).
		self.deviceFactoryXml = None
		deviceFactory = self._getChildSingleElementByTagName2(devicesTree, u"DeviceFactory", required=False, filename=filename)
		if deviceFactory is not None:
			# Test to make sure Name, ButtonTitle, and ConfigUI all exist:
			nameElem = self._getChildSingleElementByTagName2(deviceFactory, u"Name", required=True, filename=filename)
			buttonElem = self._getChildSingleElementByTagName2(deviceFactory, u"ButtonTitle", required=True, filename=filename)
			configElem = self._getChildSingleElementByTagName2(deviceFactory, u"ConfigUI", required=True, filename=filename)
			if configElem is not None:
				replaceIndex = list(deviceFactory).index(configElem)
				deviceFactory.remove(configElem)
				deviceFactory.insert(replaceIndex, self._parseConfigUINode(configElem, filename=filename, returnXml=False))
			self.deviceFactoryXml = xmlTree.tostring(deviceFactory, encoding="UTF-8", method="xml")

		sortIndex = 0
		deviceElemList = self._getChildElementsByTagName2(devicesTree, u"Device")
		for device in deviceElemList:
			serverVers = self._getElementAttribute2(device, u"_minServerVers", required=False, errorIfNotAscii=False, filename=filename)
			if serverVers is not None and not PluginBase.serverVersCompatWith(serverVers):
				continue	# This version of Indigo Server isn't compatible with this object (skip it)

			deviceDict = indigo.Dict()
			deviceTypeId = self._getElementAttribute2(device, u"id", filename=filename)
			if deviceTypeId in self.devicesTypeDict:
				raise LookupError(u"Duplicate device type id (%s) found in file %s" % (deviceTypeId, filename))
			deviceDict[u"Type"] = self._getElementAttribute2(device, u"type", filename=filename)
			if deviceDict[u"Type"] not in validDeviceTypes:
				raise LookupError(u"Unknown device type in file %s" % (filename))
			deviceDict[u"Name"] = self._getElementValueByTagName2(device, u"Name", filename=filename)
			deviceDict[u"DisplayStateId"] = self._getElementValueByTagName2(device, u"UiDisplayStateId", required=False, default=u"", filename=filename)
			deviceDict[u"SortOrder"] = sortIndex
			sortIndex += 1

			configUi = self._getChildSingleElementByTagName2(device, u"ConfigUI", required=False, filename=filename)
			if configUi is not None:
				deviceDict[u"ConfigUIRawXml"] = self._parseConfigUINode(configUi, filename=filename)

			statesList = indigo.List()
			deviceStateList = self._getChildSingleElementByTagName2(device, u"States", required=False, filename=filename)
			if deviceStateList is not None:
				deviceStateElements = self._getChildElementsByTagName2(deviceStateList, u"State")
				for state in deviceStateElements:
					stateId = self._getElementAttribute2(state, u"id", filename=filename)
					triggerLabel = self._getElementValueByTagName2(state, u"TriggerLabel", required=False, default=u"", filename=filename)
					controlPageLabel = self._getElementValueByTagName2(state, u"ControlPageLabel", required=False, default=u"", filename=filename)

					disabled = False	# ToDo: need to read this?
					stateValueType = self._getChildSingleElementByTagName2(state, u"ValueType", required=True, filename=filename)
					stateValueList = self._getChildSingleElementByTagName2(stateValueType, u"List", required=False, filename=filename)
					if stateValueList is not None:
						# It must have a TriggerLabel and a ControlPageLabel
						if (triggerLabel == "") or (controlPageLabel == ""):
							raise LookupError(u"State elements must have both a TriggerLabel and a ControlPageLabel in file %s" % (filename))
						# It's an enumeration -- add an enum type for triggering off of any changes
						# to this enumeration type:
						stateDict = self.getDeviceStateDictForEnumType(stateId, triggerLabel, controlPageLabel, disabled)
						statesList.append(stateDict)

						# And add individual true/false types for triggering off every enumeration
						# value possiblity (as specified by the Option list):
						triggerLabelPrefix = self._getElementValueByTagName2(state, u"TriggerLabelPrefix", required=False, default=u"", filename=filename)
						controlPageLabelPrefix = self._getElementValueByTagName2(state, u"ControlPageLabelPrefix", required=False, default=u"", filename=filename)

						valueOptions = self._getChildElementsByTagName2(stateValueList, u"Option")
						if len(valueOptions) < 1:
							raise LookupError(u"<List> elements must have at least one <Option> element in file %s" % (filename))
						for option in valueOptions:
							if option.text is None:
								continue
							subStateId = stateId + u"." + self._getElementAttribute2(option, u"value", filename=filename)

							if len(triggerLabelPrefix) > 0:
								subTriggerLabel = triggerLabelPrefix + u" " + option.text
							else:
								subTriggerLabel = option.text

							if len(controlPageLabelPrefix) > 0:
								subControlPageLabel = controlPageLabelPrefix + u" " + option.text
							else:
								subControlPageLabel = option.text

							subDisabled = False		# ToDo: need to read this?
							subStateDict = self.getDeviceStateDictForBoolTrueFalseType(subStateId, subTriggerLabel, subControlPageLabel, subDisabled)
							statesList.append(subStateDict)
					elif stateValueType.text is not None:
						# It's not an enumeration
						stateDict = None
						valueType = stateValueType.text.lower()
						# It must have a TriggerLabel and a ControlPageLabel if it's not a separator
						if (valueType != u"separator"):
							if (triggerLabel == "") or (controlPageLabel == ""):
								raise LookupError(u"State elements must have both a TriggerLabel and a ControlPageLabel in file %s" % (filename))
						if valueType == u"boolean":
							boolType = stateValueType.get("boolType")
							boolType = boolType.lower() if boolType is not None else u""
							if boolType == u"onoff":
								stateDict = self.getDeviceStateDictForBoolOnOffType(stateId, triggerLabel, controlPageLabel, disabled)
							elif boolType == u"yesno":
								stateDict = self.getDeviceStateDictForBoolYesNoType(stateId, triggerLabel, controlPageLabel, disabled)
							elif boolType == u"onezero":
								stateDict = self.getDeviceStateDictForBoolOneZeroType(stateId, triggerLabel, controlPageLabel, disabled)
							else:
								stateDict = self.getDeviceStateDictForBoolTrueFalseType(stateId, triggerLabel, controlPageLabel, disabled)
						elif valueType == u"number" or valueType == u"float" or valueType == u"integer":
							stateDict = self.getDeviceStateDictForNumberType(stateId, triggerLabel, controlPageLabel, disabled)
						elif valueType == u"string":
							stateDict = self.getDeviceStateDictForStringType(stateId, triggerLabel, controlPageLabel, disabled)
						elif valueType == u"separator":
							stateDict = self.getDeviceStateDictForSeparator(stateId)

						if stateDict:
							statesList.append(stateDict)
					else:
						raise LookupError(u"State elements <ValueType> empty in file %s" % (filename))
			deviceDict[u"States"] = statesList

			self.devicesTypeDict[deviceTypeId] = deviceDict

	###################
	def _parseEventsXML(self, filename):
		if not self._xmlOrJsonFileExist(filename):
			return
		(eventsTree, filename) = self._xmlOrJsonParse(filename)
		if eventsTree.tag != "Events":
			raise LookupError(u"Incorrect number of <Events> elements found in file %s" % (filename))

		sortIndex = 0
		eventElemList = self._getChildElementsByTagName2(eventsTree, u"Event")
		for event in eventElemList:
			serverVers = self._getElementAttribute2(event, u"_minServerVers", required=False, errorIfNotAscii=False, filename=filename)
			if serverVers is not None and not PluginBase.serverVersCompatWith(serverVers):
				continue	# This version of Indigo Server isn't compatible with this object (skip it)

			eventDict = indigo.Dict()
			eventTypeId = self._getElementAttribute2(event, u"id", filename=filename)
			if eventTypeId in self.eventsTypeDict:
				raise LookupError(u"Duplicate event type id (%s) found in file %s" % (eventTypeId, filename))
			try:
				eventDict[u"Name"] = self._getElementValueByTagName2(event, u"Name", filename=filename)
			except ValueError:
				# It's missing <Name> so treat it as a separator
				eventDict[u"Name"] = u" - "
			eventDict[u"SortOrder"] = sortIndex
			sortIndex += 1

			configUi = self._getChildSingleElementByTagName2(event, u"ConfigUI", required=False, filename=filename)
			if configUi is not None:
				eventDict[u"ConfigUIRawXml"] = self._parseConfigUINode(configUi, filename=filename)

			self.eventsTypeDict[eventTypeId] = eventDict

	###################
	def _parseActionsXML(self, filename):
		if not self._xmlOrJsonFileExist(filename):
			return
		(actionsTree, filename) = self._xmlOrJsonParse(filename)
		if actionsTree.tag != "Actions":
			raise LookupError(u"Incorrect number of <Actions> elements found in file %s" % (filename))

		sortIndex = 0
		actionElemList = self._getChildElementsByTagName2(actionsTree, u"Action")
		for action in actionElemList:
			serverVers = self._getElementAttribute2(action, u"_minServerVers", required=False, errorIfNotAscii=False, filename=filename)
			if serverVers is not None and not PluginBase.serverVersCompatWith(serverVers):
				continue	# This version of Indigo Server isn't compatible with this object (skip it)

			actionDict = indigo.Dict()
			actionTypeId = self._getElementAttribute2(action, u"id", filename=filename)
			if actionTypeId in self.actionsTypeDict:
				raise LookupError(u"Duplicate action type id (%s) found in file %s" % (actionTypeId, filename))

			try:
				actionDict[u"Name"] = self._getElementValueByTagName2(action, u"Name", filename=filename)
				actionDict[u"CallbackMethod"] = self._getElementValueByTagName2(action, u"CallbackMethod", required=False, default=u"", filename=filename)
				actionDict[u"DeviceFilter"] = self._getElementAttribute2(action, u"deviceFilter", required=False, default=u"", filename=filename)
			except ValueError:
				# It's missing <Name> so treat it as a separator
				actionDict[u"Name"] = u" - "
				actionDict[u"CallbackMethod"] = u""
				actionDict[u"DeviceFilter"] = u""
			actionDict[u"UiPath"] = self._getElementAttribute2(action, u"uiPath", required=False, filename=filename)
			actionDict[u"PrivateUiPath"] = self._getElementAttribute2(action, u"privateUiPath", required=False, filename=filename)
			actionDict[u"SortOrder"] = sortIndex
			sortIndex += 1

			configUi = self._getChildSingleElementByTagName2(action, u"ConfigUI", required=False, filename=filename)
			if configUi is not None:
				actionDict[u"ConfigUIRawXml"] = self._parseConfigUINode(configUi, filename=filename)

			self.actionsTypeDict[actionTypeId] = actionDict

	################################################################################
	########################################
	def doesPrefsConfigUiExist(self):
		return self._xmlOrJsonFileExist(kPluginConfigFilename)

	def getPrefsConfigUiXml(self):
		(configUiTree, filename) = self._xmlOrJsonParse(kPluginConfigFilename)
		if configUiTree.tag != "PluginConfig":
			raise LookupError(u"%s file must have one root level <PluginConfig> node" % (filename))
		return self._parseConfigUINode(configUiTree, filename=filename)

	def getPrefsConfigUiValues(self):
		valuesDict = self.pluginPrefs
		errorMsgDict = indigo.Dict()
		return (valuesDict, errorMsgDict)

	def validatePrefsConfigUi(self, valuesDict):
		return (True, valuesDict)
		#	Or if UI is not valid use:
		# errorMsgDict = indigo.Dict()
		# errorMsgDict[u"someUiFieldId"] = u"sorry but you MUST check this checkbox!"
		# return (False, valuesDict, errorMsgDict)

	def closedPrefsConfigUi(self, valuesDict, userCancelled):
		return

	def savePluginPrefs(self):
		indigo.server.savePluginPrefs()

	########################################
	def getMenuItemsList(self):
		return self.menuItemsList

	def getMenuActionConfigUiXml(self, menuId):
		if menuId in self.menuItemsDict:
			xmlRaw = self.menuItemsDict[menuId][u"ConfigUIRawXml"]
			return xmlRaw
		return None

	def getMenuActionConfigUiValues(self, menuId):
		valuesDict = indigo.Dict()
		errorMsgDict = indigo.Dict()
		return (valuesDict, errorMsgDict)

# Currently, menu actions never validate UI on closure. If this changes at some
# point then we'll need these:
#
#	def validateMenuActionConfigUi(self, valuesDict, menuId):
#		return (True, valuesDict)
#
#	def closedMenuActionConfigUi(self, valuesDict, userCancelled, menuId):
#		return

	########################################
	def getDevicesDict(self):
		return self.devicesTypeDict

	def getDeviceStateList(self, dev):
		if dev.deviceTypeId in self.devicesTypeDict:
			return self.devicesTypeDict[dev.deviceTypeId][u"States"]
		return None

	def getDeviceDisplayStateId(self, dev):
		if dev.deviceTypeId in self.devicesTypeDict:
			return self.devicesTypeDict[dev.deviceTypeId][u"DisplayStateId"]
		return None

	def getDeviceTypeClassName(self, typeId):
		if typeId in self.devicesTypeDict:
			return self.devicesTypeDict[typeId][u"Type"]
		return None

	###################
	def getDeviceConfigUiXml(self, typeId, devId):
		if typeId in self.devicesTypeDict:
			return self.devicesTypeDict[typeId][u"ConfigUIRawXml"]
		return None

	def getDeviceConfigUiValues(self, pluginProps, typeId, devId):
		valuesDict = pluginProps
		errorMsgDict = indigo.Dict()
		return (valuesDict, errorMsgDict)

	def validateDeviceConfigUi(self, valuesDict, typeId, devId):
		return (True, valuesDict)
		#	Or if UI is not valid use:
		# errorMsgDict = indigo.Dict()
		# errorMsgDict[u"someUiFieldId"] = u"sorry but you MUST check this checkbox!"
		# return (False, valuesDict, errorMsgDict)

	def closedDeviceConfigUi(self, valuesDict, userCancelled, typeId, devId):
		return

	###################
	def doesDeviceFactoryExist(self):
		return self.deviceFactoryXml is not None

	def getDeviceFactoryUiXml(self):
		return self.deviceFactoryXml

	def getDeviceFactoryUiValues(self, devIdList):
		valuesDict = indigo.Dict()
		errorMsgDict = indigo.Dict()
		return (valuesDict, errorMsgDict)

	def validateDeviceFactoryUi(self, valuesDict, devIdList):
		return (True, valuesDict)
		#	Or if UI is not valid use:
		# errorMsgDict = indigo.Dict()
		# errorMsgDict[u"someUiFieldId"] = u"sorry but you MUST check this checkbox!"
		# return (False, valuesDict, errorMsgDict)

	def closedDeviceFactoryUi(self, valuesDict, userCancelled, devIdList):
		return

	########################################
	def getEventsDict(self):
		return self.eventsTypeDict

	def getEventConfigUiXml(self, typeId, eventId):
		if typeId in self.eventsTypeDict:
			return self.eventsTypeDict[typeId][u"ConfigUIRawXml"]
		return None

	def getEventConfigUiValues(self, pluginProps, typeId, eventId):
		valuesDict = pluginProps
		errorMsgDict = indigo.Dict()
		return (valuesDict, errorMsgDict)

	def validateEventConfigUi(self, valuesDict, typeId, eventId):
		return (True, valuesDict)
		#	Or if UI is not valid use:
		# errorMsgDict = indigo.Dict()
		# errorMsgDict[u"someUiFieldId"] = u"sorry but you MUST check this checkbox!"
		# return (False, valuesDict, errorMsgDict)

	def closedEventConfigUi(self, valuesDict, userCancelled, typeId, eventId):
		return

	########################################
	def getActionsDict(self):
		return self.actionsTypeDict

	def getActionCallbackMethod(self, typeId):
		if typeId in self.actionsTypeDict:
			return self.actionsTypeDict[typeId][u"CallbackMethod"]
		return None

	def getActionConfigUiXml(self, typeId, devId):
		if typeId in self.actionsTypeDict:
			return self.actionsTypeDict[typeId][u"ConfigUIRawXml"]
		return None

	def getActionConfigUiValues(self, pluginProps, typeId, devId):
		valuesDict = pluginProps
		errorMsgDict = indigo.Dict()
		return (valuesDict, errorMsgDict)

	def validateActionConfigUi(self, valuesDict, typeId, devId):
		return (True, valuesDict)
		#	Or if UI is not valid use:
		# errorMsgDict = indigo.Dict()
		# errorMsgDict[u"someUiFieldId"] = u"sorry but you MUST check this checkbox!"
		# return (False, valuesDict, errorMsgDict)

	def closedActionConfigUi(self, valuesDict, userCancelled, typeId, devId):
		return

	################################################################################
	########################################
	def _deviceEnumAndStartComm(self):
		for elem in indigo.devices.iter(self.pluginId):
			if elem.configured and elem.enabled:
				try:
					self.deviceStartComm(elem)
				except Exception, e:
					self.logger.error(u"exception in deviceStartComm(%s): %s" % (elem.name, unicode(e)))
				except:
					self.logger.error(u"exception in deviceStartComm(%s)" % (elem.name,))

	def _deviceEnumAndStopComm(self):
		for elem in indigo.devices.iter(self.pluginId):
			if elem.configured and elem.enabled:
				try:
					self.deviceStopComm(elem)
				except Exception, e:
					self.logger.error(u"exception in deviceStopComm(%s): %s" % (elem.name, unicode(e)))
				except:
					self.logger.error(u"exception in deviceStopComm(%s)" % (elem.name,))

	def didDeviceCommPropertyChange(self, origDev, newDev):
		# Return True if a plugin related property changed from
		# origDev to newDev. Examples would be serial port,
		# IP address, etc. By default we assume all properties
		# are comm related, but plugin can subclass to provide
		# more specific/optimized testing. The return val of
		# this method will effect when deviceStartComm() and
		# deviceStopComm() are called.
		if origDev.pluginProps != newDev.pluginProps:
			return True
		return False

	def deviceStartComm(self, dev):
		# self.logger.debug(u"deviceStartComm: " + dev.name)
		pass

	def deviceStopComm(self, dev):
		# self.logger.debug(u"deviceStopComm: " + dev.name)
		pass

	def deviceCreated(self, dev):
		# self.logger.debug(u"deviceCreated: \n" + unicode(dev))
		if dev.pluginId != self.pluginId:
			return		# device is not plugin based -- bail out

		if dev.configured and dev.enabled:
			self.deviceStartComm(dev)

	def deviceDeleted(self, dev):
		# self.logger.debug(u"deviceDeleted: \n" + unicode(dev))
		if dev.pluginId != self.pluginId:
			return		# device is not plugin based -- bail out

		if dev.configured and dev.enabled:
			self.deviceStopComm(dev)

	def deviceUpdated(self, origDev, newDev):
		# self.logger.debug(u"deviceUpdated orig: \n" + unicode(origDev))
		# self.logger.debug(u"deviceUpdated new: \n" + unicode(newDev))
		origDevPluginId = origDev.pluginId
		newDevPluginId = newDev.pluginId
		if origDevPluginId != self.pluginId and newDevPluginId != self.pluginId:
			return		# neither is a plugin based device -- bail out

		origDevTypeId = origDev.deviceTypeId
		newDevTypeId = newDev.deviceTypeId

		commPropChanged = False
		if origDevPluginId != newDevPluginId:
			commPropChanged = True
		elif origDevTypeId != newDevTypeId:
			commPropChanged = True
		elif (origDev.configured and origDev.enabled) != (newDev.configured and newDev.enabled):
			commPropChanged = True
		elif newDev.configured:
			commPropChanged = self.didDeviceCommPropertyChange(origDev, newDev)

		if not commPropChanged:
			return		# no comm related properties changed -- bail out

		# If we get this far then there was a significant enough
		# change (property, pluginId, enable state) to warrant
		# a call to stop the previous device comm and restart
		# the new device comm.
		if origDevPluginId == self.pluginId:
			if origDev.configured and origDev.enabled:
				self.deviceStopComm(origDev)
		if newDevPluginId == self.pluginId:
			if newDev.configured and newDev.enabled:
				self.deviceStartComm(newDev)

	########################################
	def _triggerGetPluginId(self, trigger):
		if not isinstance(trigger, indigo.PluginEventTrigger):
			return None
		return trigger.pluginId

	def _triggerGetPluginTypeId(self, trigger):
		if not isinstance(trigger, indigo.PluginEventTrigger):
			return None
		return trigger.pluginTypeId

	def _triggerEnumAndStartProcessing(self):
		for elem in indigo.triggers.iter(self.pluginId):
			if elem.configured and elem.enabled:
				try:
					self.triggerStartProcessing(elem)
				except Exception, e:
					self.logger.error(u"exception in triggerStartProcessing(%s): %s" % (elem.name, unicode(e)))
				except:
					self.logger.error(u"exception in triggerStartProcessing(%s)" % (elem.name,))

	def _triggerEnumAndStopProcessing(self):
		for elem in indigo.triggers.iter(self.pluginId):
			if elem.configured and elem.enabled:
				try:
					self.triggerStopProcessing(elem)
				except Exception, e:
					self.logger.error(u"exception in triggerStopProcessing(%s): %s" % (elem.name, unicode(e)))
				except:
					self.logger.error(u"exception in triggerStopProcessing(%s)" % (elem.name,))

	def didTriggerProcessingPropertyChange(self, origTrigger, newTrigger):
		# Return True if a plugin related property changed from
		# origTrigger to newTrigger. Examples would be serial port,
		# IP address, etc. By default we assume all properties
		# are comm related, but plugin can subclass to provide
		# more specific/optimized testing. The return val of
		# this method will effect when triggerStartProcessing() and
		# triggerStopProcessing() are called.
		if origTrigger.pluginProps != newTrigger.pluginProps:
			return True
		return False

	def triggerStartProcessing(self, trigger):
		# self.logger.debug(u"triggerStartProcessing: " + trigger.name)
		pass

	def triggerStopProcessing(self, trigger):
		# self.logger.debug(u"triggerStopProcessing: " + trigger.name)
		pass

	def triggerCreated(self, trigger):
		# self.logger.debug(u"triggerCreated: \n" + unicode(trigger))
		if self._triggerGetPluginId(trigger) != self.pluginId:
			return		# trigger is not plugin based -- bail out

		if trigger.configured and trigger.enabled:
			self.triggerStartProcessing(trigger)

	def triggerDeleted(self, trigger):
		# self.logger.debug(u"triggerDeleted: \n" + unicode(trigger))
		if self._triggerGetPluginId(trigger) != self.pluginId:
			return		# trigger is not plugin based -- bail out

		if trigger.configured and trigger.enabled:
			self.triggerStopProcessing(trigger)

	def triggerUpdated(self, origTrigger, newTrigger):
		# self.logger.debug(u"triggerUpdated orig: \n" + unicode(origTrigger))
		# self.logger.debug(u"triggerUpdated new: \n" + unicode(newTrigger))
		origTriggerPluginId = self._triggerGetPluginId(origTrigger)
		newTriggerPluginId = self._triggerGetPluginId(newTrigger)
		if origTriggerPluginId != self.pluginId and newTriggerPluginId != self.pluginId:
			return		# neither is a plugin based trigger -- bail out

		origTriggerTypeId = self._triggerGetPluginTypeId(origTrigger)
		newTriggerTypeId = self._triggerGetPluginTypeId(newTrigger)

		processingPropChanged = False
		if origTriggerPluginId != newTriggerPluginId:
			processingPropChanged = True
		elif origTriggerTypeId != newTriggerTypeId:
			processingPropChanged = True
		elif (origTrigger.configured and origTrigger.enabled) != (newTrigger.configured and newTrigger.enabled):
			processingPropChanged = True
		elif newTrigger.configured:
			processingPropChanged = self.didTriggerProcessingPropertyChange(origTrigger, newTrigger)

		if not processingPropChanged:
			return		# no processing related properties changed -- bail out

		# If we get this far then there was a significant enough
		# change (property, pluginId, enable state) to warrant
		# a call to stop the previous trigger processing and restart
		# the new trigger processing.
		if origTriggerPluginId == self.pluginId:
			if origTrigger.configured and origTrigger.enabled:
				self.triggerStopProcessing(origTrigger)
		if newTriggerPluginId == self.pluginId:
			if newTrigger.configured and newTrigger.enabled:
				self.triggerStartProcessing(newTrigger)

	########################################
	def scheduleCreated(self, schedule):
		# self.logger.debug(u"scheduleCreated: \n" + unicode(schedule))
		pass

	def scheduleDeleted(self, schedule):
		# self.logger.debug(u"scheduleDeleted: \n" + unicode(schedule))
		pass

	def scheduleUpdated(self, origSchedule, newSchedule):
		# self.logger.debug(u"scheduleUpdated orig: \n" + unicode(origSchedule))
		# self.logger.debug(u"scheduleUpdated new: \n" + unicode(newSchedule))
		pass

	########################################
	def actionGroupCreated(self, group):
		# self.logger.debug(u"actionGroupCreated: \n" + unicode(group))
		pass

	def actionGroupDeleted(self, group):
		# self.logger.debug(u"actionGroupDeleted: \n" + unicode(group))
		pass

	def actionGroupUpdated(self, origGroup, newGroup):
		# self.logger.debug(u"actionGroupUpdated orig: \n" + unicode(origGroup))
		# self.logger.debug(u"actionGroupUpdated new: \n" + unicode(newGroup))
		pass

	########################################
	def controlPageCreated(self, page):
		# self.logger.debug(u"controlPageCreated: \n" + unicode(page))
		pass

	def controlPageDeleted(self, page):
		# self.logger.debug(u"controlPageDeleted: \n" + unicode(page))
		pass

	def controlPageUpdated(self, origPage, newPage):
		# self.logger.debug(u"controlPageUpdated orig: \n" + unicode(origPage))
		# self.logger.debug(u"controlPageUpdated new: \n" + unicode(newPage))
		pass

	########################################
	def variableCreated(self, var):
		# self.logger.debug(u"variableCreated: \n" + unicode(var))
		pass

	def variableDeleted(self, var):
		# self.logger.debug(u"variableDeleted: \n" + unicode(var))
		pass

	def variableUpdated(self, origVar, newVar):
		# self.logger.debug(u"variableUpdated orig: \n" + unicode(origVar))
		# self.logger.debug(u"variableUpdated new: \n" + unicode(newVar))
		pass

	################################################################################
	########################################
	def applicationWithBundleIdentifier(self, bundleID):
		from ScriptingBridge import SBApplication
		return SBApplication.applicationWithBundleIdentifier_(bundleID)

	########################################
	def browserOpen(self, url):
		# We originally tried using webbrowser.open_new(url) but it
		# seems quite buggy, so instead we'll let IPH handle it:
		indigo.host.browserOpen(url)

	########################################
	def _insertVariableValue(self, matchobj):
		try:
			theVarValue = indigo.variables[int(matchobj.group(1))].value
		except:
			theVarValue = ""
			self.logger.error(u"Variable id " + matchobj.group(1) + u" not found for substitution")
		return theVarValue

	###################
	def substituteVariable(self, inString, validateOnly=False):
		validated = True
		variableValue = None
		stringParts = inString.split("%%")
		for substr in stringParts:
			if substr[0:2] == "v:":
				varNameTuple = substr.split(":")
				varIdString = varNameTuple[1]
				if varIdString.find(" ") < 0:
					try:
						varId = int(varIdString)
						theVariable = indigo.variables.get(varId, None)
						if theVariable is None:
							validated = False
						else:
							variableValue = theVariable.value
					except:
						validated = False
				else:
					validated = False
		if validateOnly:
			if validated:
				return (validated,)
			else:
				return (validated, u"Either a variable ID doesn't exist or there's a substitution format error")
		else:
			p = re.compile("\%%v:([0-9]*)%%")
			newString = p.sub(self._insertVariableValue, inString)
			return newString

	########################################
	def _insertStateValue(self, matchobj):
		try:
			theStateValue = unicode(indigo.devices[int(matchobj.group(1))].states[matchobj.group(2)])
		except:
			theStateValue = ""
			self.logger.error(u"Device id " + matchobj.group(1) + u" or state id " + matchobj.group(2) + u" not found for substitution")
		return theStateValue

	###################
	def substituteDeviceState(self, inString, validateOnly=False):
		validated = True
		stateValue = None
		stringParts = inString.split("%%")
		for substr in stringParts:
			if substr[0:2] == "d:":
				devParts = substr.split(":")
				if (len(devParts) != 3):
					validated = False
				else:
					devIdString = devParts[1]
					devStateName = devParts[2]
					if devIdString.find(" ") < 0:
						try:
							devId = int(devIdString)
							theDevice = indigo.devices.get(devId, None)
							if theDevice is None:
								validated = False
							else:
								stateValue = theDevice.states[devStateName]
						except:
							validated = False
					else:
						validated = False
		if validateOnly:
			if validated:
				return (validated,)
			else:
				return (validated, u"Either a device ID or state doesn't exist or there's a substitution format error")
		else:
			p = re.compile("\%%d:([0-9]*):([A-z0-9\.]*)%%")
			newString = p.sub(self._insertStateValue, inString)
			return newString

	########################################
	def substitute(self, inString, validateOnly=False):
		results = self.substituteVariable(inString, validateOnly)
		if isinstance(results, tuple):
			if results[0]:
				results = inString
			else:
				return results
		results = self.substituteDeviceState(results, validateOnly)
		return results

	########################################
	# Utility method to be called from plugin's validatePrefsConfigUi, validateDeviceConfigUi, etc.
	# methods. Used to make sure that a valid serial port is chosen. Caller should pass any non-None
	# tuple results up to the IPH caller (if None is returned then serial UI is valid and they
	# should continue with any other validation).
	def validateSerialPortUi(self, valuesDict, errorsDict, fieldId):
		connTypeKey = fieldId + u'_serialConnType'
		uiAddressKey = fieldId + u'_uiAddress'
		if valuesDict[connTypeKey] == u"local":
			localKey = fieldId + u'_serialPortLocal'
			valuesDict[uiAddressKey] = valuesDict[localKey]
			if len(valuesDict[localKey]) == 0:
				# User has not selected a valid serial port -- show an error.
				errorsDict[localKey] = u"Select a valid serial port. If none are listed, then make sure you have installed the FTDI VCP driver."
				return False
		elif valuesDict[connTypeKey] == u"netSocket":
			netSocketKey = fieldId + u'_serialPortNetSocket'
			netSocket = valuesDict.get(netSocketKey, u"")
			netSocket = netSocket.replace(u"socket://", u"")
			netSocket = netSocket.replace(u"rfc2217://", u"")
			valuesDict[netSocketKey] = u"socket://" + netSocket
			valuesDict[uiAddressKey] = netSocket
			try:
				if len(netSocket) == 0:
					raise ValueError("empty URL")
				stripped = netSocket
				if '/' in stripped:
					stripped, options = stripped.split('/', 1)
				host, port = stripped.split(':', 1)
				port = int(port)
				if not 0 <= port < 65536:
					raise ValueError("port not in range 0...65535")
			except ValueError:
				errorsDict[netSocketKey] = u"Enter a valid network IP address and port for the remote serial server (ex: socket://192.168.1.160:8123)."
				return False
		elif valuesDict[connTypeKey] == u"netRfc2217":
			netRfc2217Key = fieldId + u'_serialPortNetRfc2217'
			netRfc2217 = valuesDict.get(netRfc2217Key, u"")
			netRfc2217 = netRfc2217.replace(u"socket://", u"")
			netRfc2217 = netRfc2217.replace(u"rfc2217://", u"")
			valuesDict[netRfc2217Key] = u"rfc2217://" + netRfc2217
			valuesDict[uiAddressKey] = netRfc2217
			try:
				if len(netRfc2217) == 0:
					raise ValueError("empty URL")
				stripped = netRfc2217
				if '/' in stripped:
					stripped, options = stripped.split('/', 1)
				host, port = stripped.split(':', 1)
				port = int(port)
				if not 0 <= port < 65536:
					raise ValueError("port not in range 0...65535")
			except ValueError:
				errorsDict[netRfc2217Key] = u"Enter a valid network IP address and port for the remote serial server (ex: rfc2217://192.168.1.160:8123)."
				return False
		else:
			valuesDict[uiAddressKey] = u""
			errorsDict[connTypeKey] = u"Valid serial connection type not selected."
			return False
		return True

	def getSerialPortUrl(self, propsDict, fieldId):
		try:
			connTypeKey = fieldId + u'_serialConnType'
			if propsDict[connTypeKey] == u"local":
				localKey = fieldId + u'_serialPortLocal'
				return propsDict[localKey]
			elif propsDict[connTypeKey] == u"netSocket":
				netSocketKey = fieldId + u'_serialPortNetSocket'
				netSocket = propsDict.get(netSocketKey, u"")
				if not netSocket.lower().startswith("socket://"):
					netSocket = u"socket://" + netSocket
				return netSocket
			elif propsDict[connTypeKey] == u"netRfc2217":
				netRfc2217Key = fieldId + u'_serialPortNetRfc2217'
				netRfc2217 = propsDict.get(netRfc2217Key, u"")
				if not netRfc2217.lower().startswith("rfc2217://"):
					netRfc2217 = u"rfc2217://" + netRfc2217
				return netRfc2217
		except:
			return u""

	# Call through to pySerial's .Serial() contructor, but handle error exceptions by
	# logging them and returning None. No exceptions will be raised.
	def openSerial(self, ownerName, portUrl, baudrate, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=None, xonxoff=False, rtscts=False, writeTimeout=None, dsrdtr=False, interCharTimeout=None, errorLogFunc=None):
		if errorLogFunc is None:
			errorLogFunc = self.logger.error

		if not isinstance(portUrl, (str, unicode)) or len(portUrl) == 0:
			errorLogFunc(u"valid serial port not selected for \"%s\"" % (ownerName,))
			return None

		try:
			return serial.serial_for_url(portUrl, baudrate=baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits, timeout=timeout, xonxoff=xonxoff, rtscts=rtscts, writeTimeout=writeTimeout, dsrdtr=dsrdtr, interCharTimeout=interCharTimeout)
		except Exception, exc:
			portUrl_lower = portUrl.lower()
			errorLogFunc(u"\"%s\" serial port open error: %s" % (ownerName, unicode(exc)))
			if u"no 35" in unicode(exc):
				errorLogFunc(u"the specified serial port is used by another interface or device")
			elif portUrl_lower.startswith('rfc2217://') or portUrl_lower.startswith('socket://'):
				errorLogFunc(u"make sure remote serial server IP address and port number are correct")
			else:
				errorLogFunc(u"make sure the USB virtual serial port driver (ex: FTDI driver) is installed and correct port is selected")
			return None


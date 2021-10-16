#! /usr/bin/env python
# -*- coding: utf-8 -*-
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkIndigoParamDefn by RogueProeliator <adam.d.ashe@gmail.com>
# 	This class stores the definition of a parameter coming from Indigo - for an action,
#	device configuration, plugin configuration, etc. It is used so that the base classes
#	may automatically handle parameter functions (such as validation) that normally would
#	have to be written into each plugin
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////

#/////////////////////////////////////////////////////////////////////////////////////////
#region Python Imports
import os
import re
import sys

if sys.version_info > (3,):
	import urllib.request as urlopen
else:
	from urllib2 import urlopen

try:
	import indigo
except:
	pass

from .RPFrameworkUtils import to_unicode
from .RPFrameworkUtils import to_str

#endregion
#/////////////////////////////////////////////////////////////////////////////////////////

#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkIndigoParamDefn
#	This class stores the definition of a parameter coming from Indigo - for an action,
#	device configuration, plugin configuration, etc.
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
class RPFrameworkIndigoParamDefn(object):
	#/////////////////////////////////////////////////////////////////////////////////////////
	#region Constants and Configuration Variables
	ParamTypeInteger         = 0
	ParamTypeFloat           = 1
	ParamTypeBoolean         = 2
	ParamTypeString          = 3
	ParamTypeOSDirectoryPath = 4
	ParamTypeIPAddress       = 5
	ParamTypeList            = 6
	ParamTypeOSFilePath      = 7

	#endregion
	#/////////////////////////////////////////////////////////////////////////////////////////
	
	#/////////////////////////////////////////////////////////////////////////////////////
	#region Construction and Destruction Methods
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor allows passing in the data that makes up the definition of the paramType
	# (with the type and ID being the only two required fields
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, indigoId, paramType, isRequired=False, defaultValue="", minValue=0, maxValue=2147483647, validationExpression=u'', invalidValueMessage=u''):
		self.indigoId             = indigoId
		self.paramType            = paramType
		self.isRequired           = isRequired
		self.defaultValue         = defaultValue
		self.minValue             = minValue
		self.maxValue             = maxValue
		self.validationExpression = validationExpression
		self.invalidValueMessage  = invalidValueMessage

	#endregion
	#/////////////////////////////////////////////////////////////////////////////////////
		
	#/////////////////////////////////////////////////////////////////////////////////////
	#region Validation Methods
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will return a boolean indicating if the provided value is valid
	# according to the parameter type and configuration. It is assumed that the proposed
	# value will always be a string!
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def isValueValid(self, proposedValue):
		# if the value is required but empty then error here
		if proposedValue == None or proposedValue == u'':
			return not self.isRequired
		
		# now validate that the type is correct...
		if self.paramType == RPFrameworkIndigoParamDefn.ParamTypeInteger:
			try:
				proposedIntValue = int(proposedValue)
				if proposedIntValue < self.minValue or proposedIntValue > self.maxValue:
					raise u'Param value not in range'
				return True
			except:
				return False
				
		elif self.paramType == RPFrameworkIndigoParamDefn.ParamTypeFloat:
			try:
				proposedFltValue = float(proposedValue)
				if proposedFltValue < self.minValue or proposedFltValue > self.maxValue:
					raise u'Param value not in range'
				return True
			except:
				return False
				
		elif self.paramType == RPFrameworkIndigoParamDefn.ParamTypeBoolean:
			if type(proposedValue) is bool:
				return True
			else:
				return proposedValue.lower() == u'true'
			
		elif self.paramType == RPFrameworkIndigoParamDefn.ParamTypeOSDirectoryPath:
			# validate that the path exists... and that it is a directory
			return os.path.isdir(to_str(proposedValue))
			
		elif self.paramType == RPFrameworkIndigoParamDefn.ParamTypeOSFilePath:
			# validate that the file exists (and that it is a file)
			return os.path.isfile(to_str(proposedValue))
		
		elif self.paramType == RPFrameworkIndigoParamDefn.ParamTypeIPAddress:
			# validate the IP address using IPv4 standards for now...
			return self.isIPv4Valid(to_str(proposedValue))
			
		elif self.paramType == RPFrameworkIndigoParamDefn.ParamTypeList:
			# validate that the list contains between the minimum and maximum
			# number of entries
			if len(proposedValue) < self.minValue or len(proposedValue) > self.maxValue:
				return False
			else:
				return True
			
		else:
			# default is a string value... so this will need to check against the
			# validation expression, if set, and string length
			if self.validationExpression != u'':
				if re.search(self.validationExpression, proposedValue, re.I) == None:
					return False
					
			strLength = len(proposedValue)
			if strLength < self.minValue or strLength > self.maxValue:
				return False
				
			# if string processing makes it here then all is good
			return True
			
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will validate whether or not an IP address is valid as a IPv4 addr
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def isIPv4Valid(self, ip):
		# Make sure a value was entered for the address... an IPv4 should require at least
		# 7 characters (0.0.0.0)
		if len(ip) < 7:
			return False
			
		# separate the IP address into its components... this limits the format for the
		# user input but is using a fairly standard notation so acceptable
		addressParts = ip.split(u'.')	
		if len(addressParts) != 4:
			return False
				
		for part in addressParts:
			try:
				part = int(part)
				if part < 0 or part > 255:
					return False
			except ValueError:
				return False
				
		# if we make it here, the input should be valid
		return True

	#endregion
	#/////////////////////////////////////////////////////////////////////////////////////

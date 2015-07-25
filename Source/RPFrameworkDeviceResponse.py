#! /usr/bin/env python
# -*- coding: utf-8 -*-
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkDeviceResponse by RogueProeliator <rp@rogueproeliator.com>
# 	Class for all RogueProeliator's "incoming" responses such that they may be
#	automatically processed by base classes
#	
#	Version 1.0.0 [10-18-2013]:
#		Initial release of the device framework
#	Version 1.0.6:
#		Added error catching surrounding effect execution; now outputs to log instead of
#			crashing on error
#
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////


#/////////////////////////////////////////////////////////////////////////////////////////
# Python imports
#/////////////////////////////////////////////////////////////////////////////////////////
import indigo
import math
import re
import RPFrameworkCommand
import RPFrameworkPlugin


#/////////////////////////////////////////////////////////////////////////////////////////
# Constants and configuration variables
#/////////////////////////////////////////////////////////////////////////////////////////
RESPONSE_EFFECT_UPDATESTATE = "updateDeviceState"
RESPONSE_EFFECT_QUEUECOMMAND = "queueCommand"
RESPONSE_EFFECT_CALLBACK = "eventCallback"


#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkDeviceResponse
#	Class for all RogueProeliator's "incoming" responses such that they may be
#	automatically processed by base classes
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
class RPFrameworkDeviceResponse(object):
	
	#/////////////////////////////////////////////////////////////////////////////////////
	# Class construction and destruction methods
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor allows passing in the data that makes up the response object
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, responseId, criteriaFormatString, matchExpression, respondToActionId=""):
		self.responseId = responseId
		self.criteriaFormatString = criteriaFormatString
		self.respondToActionId = respondToActionId
		self.matchExpression = matchExpression
		self.matchResultEffects = list()
		
	
	#/////////////////////////////////////////////////////////////////////////////////////
	# Effect definition functions
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Allows an outside class to add a new effect to this response object
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def addResponseEffect(self, effect):
		self.matchResultEffects.append(effect)
		
	
	#/////////////////////////////////////////////////////////////////////////////////////
	# Testing and Execution functions
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will test the given input to determine if it is a match for the
	# response definition
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def isResponseMatch(self, responseObj, rpCommand, rpDevice, rpPlugin):
		if self.criteriaFormatString is None or self.criteriaFormatString == "" or self.matchExpression is None or self.matchExpression == "":
			# we only need to look at the action...
			if self.respondToActionId == "" or self.respondToActionId == rpCommand.parentAction.indigoActionId:
				return True
			else:
				return False
				
		matchCriteriaTest = self.substituteCriteriaFormatString(self.criteriaFormatString, responseObj, rpCommand, rpDevice, rpPlugin)
		matchObj = re.match(self.matchExpression, matchCriteriaTest, re.I)
		return (matchObj is not None) and (self.respondToActionId == "" or self.respondToActionId == rpCommand.parentAction.indigoActionId)
	
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will generate the criteria to test based upon the response and the
	# response definition criteria
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def substituteCriteriaFormatString(self, formatString, responseObj, rpCommand, rpDevice, rpPlugin):
		substitutedCriteria = formatString
		if substitutedCriteria is None:
			return ""
		
		# substitute the response/command object values as those are
		# specific to commands
		if rpCommand is not None:
			substitutedCriteria = substitutedCriteria.replace("%cp:name%", rpCommand.commandName)
			substitutedCriteria = substitutedCriteria.replace("%cp:payload%", str(rpCommand.commandPayload))
		
		if isinstance(responseObj, (str, unicode)):
			substitutedCriteria = substitutedCriteria.replace("%cp:response%", responseObj)
		
		# substitute the standard RPFramework substitutions
		substitutedCriteria = rpPlugin.substituteIndigoValues(substitutedCriteria, rpDevice, None)
		
		#return the result back to the caller
		return substitutedCriteria
			
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will execute the effects of the response; it is assuming that it is
	# a match (it will not re-match)
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def executeEffects(self, responseObj, rpCommand, rpDevice, rpPlugin):
		for effect in self.matchResultEffects:
			# processing for this effect is dependent upon the type
			try:
				if effect.effectType == RESPONSE_EFFECT_UPDATESTATE:
					# this effect should update a device state (param) with a value as formated
					newStateValueString = self.substituteCriteriaFormatString(effect.updateValueFormatString, responseObj, rpCommand, rpDevice, rpPlugin)
					if effect.evalUpdateValue == True:
						newStateValue = eval(newStateValueString)
					else:
						newStateValue = newStateValueString
						
					# the effect may have a UI value set... if not leave at an empty string so that
					# we don't attempt to update it
					newStateUIValue = ""
					if effect.updateValueFormatExString != "":
						newStateUIValueString = self.substituteCriteriaFormatString(effect.updateValueFormatExString, responseObj, rpCommand, rpDevice, rpPlugin)
						if effect.evalUpdateValue == True:
							newStateUIValue = eval(newStateUIValueString)
						else:
							newStateUIValue = newStateUIValueString 
				
					# update the state...
					if newStateUIValue == "":
						rpPlugin.logDebugMessage("Effect execution: Update state '" + effect.updateParam + "' to '" + str(newStateValue) + "'", RPFrameworkPlugin.DEBUGLEVEL_MED)
						rpDevice.indigoDevice.updateStateOnServer(key=effect.updateParam, value=newStateValue)
					else:
						rpPlugin.logDebugMessage("Effect execution: Update state '" + effect.updateParam + "' to '" + str(newStateValue) + "' with UIValue '" + str(newStateUIValue) + "'", RPFrameworkPlugin.DEBUGLEVEL_MED)
						rpDevice.indigoDevice.updateStateOnServer(key=effect.updateParam, value=newStateValue, uiValue=newStateUIValue)
				
				elif effect.effectType == RESPONSE_EFFECT_QUEUECOMMAND:
					# this effect will enqueue a new command... the updateParam will define the command name
					# and the updateValueFormat will define the new payload
					queueCommandName = self.substituteCriteriaFormatString(effect.updateParam, responseObj, rpCommand, rpDevice, rpPlugin)

					queueCommandPayloadStr = self.substituteCriteriaFormatString(effect.updateValueFormatString, responseObj, rpCommand, rpDevice, rpPlugin)
					if effect.evalUpdateValue == True:
						queueCommandPayload = eval(queueCommandPayloadStr)
					else:
						queueCommandPayload = queueCommandPayloadStr
				
					rpPlugin.logDebugMessage("Effect execution: Queuing command {" + queueCommandName + "}", RPFrameworkPlugin.DEBUGLEVEL_MED)
					rpDevice.queueDeviceCommand(RPFrameworkCommand.RPFrameworkCommand(queueCommandName, queueCommandPayload))
				
				elif effect.effectType == RESPONSE_EFFECT_CALLBACK:
					# this should kick off a callback to a python call on the device...
					rpPlugin.logDebugMessage("Effect execution: Calling function " + effect.updateParam, RPFrameworkPlugin.DEBUGLEVEL_MED)
					eval("rpDevice." + effect.updateParam + "(responseObj, rpCommand)")
			except:
				indigo.server.log('Error executing effect for device id ' + str(rpDevice.indigoDevice.id), isError=True)
				rpPlugin.exceptionLog()
				
	
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkDeviceResponseEffect
#	Class that defines the effects that a match against the device response will enact;
#	these are things such as updating a device state, firing an event, etc.
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
class RPFrameworkDeviceResponseEffect(object):
	
	#/////////////////////////////////////////////////////////////////////////////////////
	# Class construction and destruction methods
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor allows passing in the data that makes up the response object
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, effectType, updateParam, updateValueFormatString="", updateValueFormatExString = "", evalUpdateValue=False):
		self.effectType = effectType
		self.updateParam = updateParam
		self.updateValueFormatString = updateValueFormatString
		self.updateValueFormatExString = updateValueFormatExString
		self.evalUpdateValue = evalUpdateValue
		
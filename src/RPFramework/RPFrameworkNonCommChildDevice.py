#! /usr/bin/env python
# -*- coding: utf-8 -*-
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkNonCommChildDevice by RogueProeliator <adam.d.ashe@gmail.com>
# 	Base class for all RogueProeliator's devices which do not actively communicate but
#	rather function to pass commands along to a parent device; examples would be zones indigo
#	a multi-room audio system or zones in an alarm panel
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////

#/////////////////////////////////////////////////////////////////////////////////////////
#region Python imports
from __future__ import absolute_import
import sys

if sys.version_info > (3,):
	import queue as Queue
else:
	import Queue

try:
	import indigo
except:
	pass

from .RPFrameworkCommand import RPFrameworkCommand
from .RPFrameworkPlugin  import RPFrameworkPlugin
from .RPFrameworkDevice  import RPFrameworkDevice
from .RPFrameworkUtils   import to_unicode

#endregion
#/////////////////////////////////////////////////////////////////////////////////////////

#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkNonCommChildDevice
#	Base class for all RogueProeliator's devices which do not actively communicate but
#	rather function to pass commands along to a parent device.
#
#	This function inherits the standard (communicating) device and disables those
#	functions (they should be present since the plugin will call them during the lifecycle
#	of the device)
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
class RPFrameworkNonCommChildDevice(RPFrameworkDevice):

	#/////////////////////////////////////////////////////////////////////////////////////
	#region Construction and Destruction Methods
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor called once upon plugin class receiving a command to start device
	# communication. The plugin will call other commands when needed, simply zero out the
	# member variables
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, plugin, device):
		super(RPFrameworkNonCommChildDevice, self).__init__(plugin, device)

	#/////////////////////////////////////////////////////////////////////////////////////
	# Disabled communications functions
	#/////////////////////////////////////////////////////////////////////////////////////
	def initiateCommunications(self):
		super(RPFrameworkNonCommChildDevice, self).initiateCommunications(initializeConnect=False)
		
	def terminateCommunications(self):
		pass
	
	#endregion
	#/////////////////////////////////////////////////////////////////////////////////////

	#/////////////////////////////////////////////////////////////////////////////////////
	#region Queue and Command Processing Methods	
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Add new command to queue of the PARENT object... this must be obtained from the
	# plugin...
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def queueDeviceCommand(self, command):
		parentDeviceId = int(self.indigoDevice.pluginProps[self.hostPlugin.getGUIConfigValue(self.indigoDevice.deviceTypeId, RPFrameworkPlugin.GUI_CONFIG_PARENTDEVICEIDPROPERTYNAME, u'')])
		if parentDeviceId in self.hostPlugin.managedDevices:
			self.hostPlugin.managedDevices[parentDeviceId].queueDeviceCommand(command)
	
	#endregion
	#/////////////////////////////////////////////////////////////////////////////////////
		
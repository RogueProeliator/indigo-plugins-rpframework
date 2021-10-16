# Introduction
This project aims to create a reusable framework/library of code that speeds the development (and reduces the maintenance) of plugins for Indigo Domo's home automation platform. It attempts to guide the developer into best-practices for key elements of the plugin such as:
- Execution of long-running actions on background threads
- Queued action/messaging system to handle multiple simultaneous incoming requests
- Configuring redundant handlers via configuration files instead of boilerplate code

# Installing the Framework into Your Project
The framework may be copied into a subdirectory of your plugin project and used as an included module; however, that makes maintenance and updates a bit of a chore. Instead, the recommended approach is that you add the framework as a sub-module to your project, allowing independent upgrading by pulling the latest in via standard git commands.

## Adding the Submodule to a Project
INSTRUCTIONS HERE

## Updating the RPFramework
INSTRUCTIONS HERE

# Incorporating into Plugins
Developing a plugin using the framework requires thinking slightly different than starting from scratch; it isn't harder, just a slightly different approach! The easiest thing for many people to do is follow along with an example project, which you may find INSERT LINK HERE.

## Inhert from RPFrameworkPlugin
The first step is to inherit your primary plugin from RPFrameworkPlugin, which provides most of the base functionality for the framework. In your *plugin.py* file, change the main class to:
```
class Plugin(RPFramework.RPFrameworkPlugin.RPFrameworkPlugin):
```

## Create Device (Python) Classes
The RPFramework is designed such that each device type is represented by a Python class which inherits from one of the base RPFramework device types. There are four major device base classes provided to you:
-RPFrameworkDevice (bare bones class for truly custom device)
-RPFrameworkRESTfulDevice (provides connectivity to HTTP based devices)
-RPFrameworkTelnetDevice
-RPFrameworkNonCommChildDevice (a device which represents a device that does no direct communication; such as a zone within a multi-zone receiver)

Once you have decided which base class is right for your device type(s), create a Python class for each type:
```
class MyAwesomeDevice(RPFrameworkRESTfulDevice):
```

The device classes will be mapped to your Indigo deviceTypeId's in the configuration file below. More documentation on these base classes may be found in the Wiki.

## Create the RPFramework Configuration File
You configure many of the options and behaviors of the framework using the RPFrameworkConfiguration.xml file. If you are using a standard device type such as a device that uses a JSON web service then you may be able to completely configure the device without writing a line of code!

Below is a brief overview of the major sections; the Wiki pages provide more details and a sample configuration file is available in the *docs* folder of this repository.

### GUI Configuration
This section provides some basic settings to determine how your plugin will present itself, such as customizing the included menu items.
```
<guiConfiguration>
    <showUPnPDebug>True</showUPnPDebug>
    <pluginUpdateURL><![CDATA[http://mypluginurl.com/]]></pluginUpdateURL>
</guiConfiguration>
```

### Device Mapping
Here you will map all of your devices, as defined in the Devices.xml file, to the Python classes you created in the previous step. Each device type should have an included entry
```
<deviceMapping>
    <device indigoId="mySuperAwesomeDevice" className="MyAwesomeDevice" />
    <device indigoId="mySuperAwesomeSecondDevice" className="MyAwesomeSecondDevice" />
</deviceMapping>
```

### Device Definitions
This section allows you to configure the devices themselves in order to take advantage of the framework's base functionality. Configuring your device here automatically enables features such as input validation on the Device Configuration Screen, action parameter validation, and even how the device handles responses (when using the RESTful or Telnet devices). The following sample is from the Sony Network Remote plugin which is based on the RESTful base device class.

```
<devices>
    <device indigoId="sonyTvRemoteDevice">
        <params>
            <param indigoId="httpAddress" paramType="ParamTypeString" isRequired="True">
                <validationExpression><![CDATA[^[a-z\d\. ]+$]]></validationExpression>
                <invalidValueMessage><![CDATA[Please select the device to control or enter the IP address]]></invalidValueMessage>
            </param>
            <param indigoId="httpPort" paramType="ParamTypeInteger" isRequired="True">
                <minValue>1</minValue>
                <maxValue>99999</maxValue>
                <defaultValue>80</defaultValue>
                <invalidValueMessage><![CDATA[Please enter a valid port number for the television to control]]></invalidValueMessage>
            </param>
            <param indigoId="macAddress" paramType="ParamTypeString" isRequired="False">
                <validationExpression><![CDATA[^([a-f\d]{1,2}\:){5}[a-f\d]{1,2}$]]></validationExpression>
                <invalidValueMessage><![CDATA[Please enter a valid MAC address using colon separators (aa:bb:cc:dd:ee:ff)]]></invalidValueMessage>
            </param>
        </params>
        <deviceResponses>
            <response id="getRemoteIRCommandsResp" respondToActionId="downloadRemoteCommands">
                <criteriaFormatString></criteriaFormatString>
                <matchExpression></matchExpression>
                <effects>
                    <effect effectType="RESPONSE_EFFECT_CALLBACK" evalResult="false">
                        <updateParam>remoteDeviceIRCommandListReceived</updateParam>
                        <updateValueFormat></updateValueFormat>
                    </effect>
                </effects>
            </response>
        </deviceResponses>
    </device>
</devices>
```
Please see the Wiki for detailed information regarding defining device parameters and responses.

### Actions
This section allows you to define information related to the actions that you have setup for devices within the Actions.xml file. Defining and allowing the framework to manage the actions provides you with built-in support for features such as UI validation, automatic handling of the code to execute (i.e. no need to write any code for HTTP or Telnet operations!), etc. It still allows you to call a custom function to handle the action if required, of course.
```
<actions>
    <action indigoId="sendRemoteButton">
        <commands>
            <command>
                <commandName>SOAP_REQUEST</commandName>
                <commandFormat><![CDATA[
                %dp:queryPath%
                urn:schemas-sony-com:service:IRCC:1#X_SendIRCC
                <?xml version="1.0" encoding="UTF-8"?>
                <SOAP-ENV:Envelope SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
                    <SOAP-ENV:Body>
                        <m:X_SendIRCC xmlns:m="urn:schemas-sony-com:service:IRCC:1">
                            <IRCCCode xmlns:dt="urn:schemas-microsoft-com:datatypes" dt:dt="string">%ap:buttonSelect%</IRCCCode>
                        </m:X_SendIRCC>
                    </SOAP-ENV:Body>
                </SOAP-ENV:Envelope>
                ]]></commandFormat>
            </command>
        </commands>
        <params>
            <param indigoId="buttonSelect" paramType="ParamTypeString" isRequired="True">
                <invalidValueMessage><![CDATA[Please select a button to send to the device]]></invalidValueMessage>
            </param>
        </params>
    </action>
    <action indigoId="sendPowerOnCommand">
        <commands>
            <command>
                <commandName>SENDWOLREQUEST</commandName>
                <commandFormat><![CDATA[%dp:macAddress%]]></commandFormat>
            </command>
        </commands>
    </action>
</actions>
```
More details are required for this configuration - such as what commands are available and how to configure parameters - in the Wiki area.

## Standard Configuration Files
Taking advantage of the framework's processing as defined in the above section is very easy - you need only assign the framework's handler as the callback in your *Actions.xml* and *MenuItems.xml* file. For the *Actions.xml*, simply set **executeAction** as the *CallbackMethod* for each action.
```
<Actions>
	<Action id="sendPowerOnCommand" uiPath="DeviceActions" deviceFilter="self">
		<Name>Power On</Name>
		<CallbackMethod>executeAction</CallbackMethod>
	</Action>
</Actions>
```

The framework also provides some built-in functionality for the MenuItems.xml handling, but you must still provide the UI elements. For example, in the following snippet there is no need to implement the *toggleDebugEnabled* routine as it is provided out-of-the-box.
```
<MenuItems>
    <MenuItem id="toggleDebug">
		<Name>Toggle Debugging On/Off</Name>
		<CallbackMethod>toggleDebugEnabled</CallbackMethod>
	</MenuItem>
</MenuItems>
```
For a complete list of available menu items, please see the Wiki.
#! /usr/bin/env python
# -*- coding: utf-8 -*-
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RPFrameworkNetworkingUPnP by RogueProeliator <adam.d.ashe@gmail.com>
# 	Classes that handle various aspects of Universal Plug and Play protocols such as
#	discovery of devices.
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////

#/////////////////////////////////////////////////////////////////////////////////////////
#region Python Imports
from __future__ import absolute_import
import socket
import sys

if sys.version_info > (3,):
	import http.client as httplib
	from io import StringIO
else:
	import httplib
	import StringIO

from .RPFrameworkUtils import to_unicode
from .RPFrameworkUtils import to_str

#endregion
#/////////////////////////////////////////////////////////////////////////////////////////

#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# SSDPResponse
#	Handles the request (and response) to SSDP queries initiated in order to find Network
#	devices such as Roku boxes
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
class SSDPResponse(object):
	######################################################################################
	# Internal class for creating the socket necessary to send the request
	######################################################################################
	class _FakeSocket(StringIO):
		def makefile(self, *args, **kw):
			return self
		
	def __init__(self, response):
		r = httplib.HTTPResponse(self._FakeSocket(response))
		r.begin()
		
		self.location = u''
		self.usn      = u''
		self.st       = u''
		self.server   = u''
		self.cache    = u''
		
		if r.getheader("location") is not None:
			self.location = to_unicode(r.getheader("location"))
			
		if r.getheader("usn") is not None:
			self.usn = to_unicode(r.getheader("usn"))
	
		if r.getheader("st") is not None:
			self.st = to_unicode(r.getheader("st"))
	
		if r.getheader("server") is not None:
			self.server = to_unicode(r.getheader("server"))
		
		if r.getheader("cache-control") is not None:
			try:
				cacheControlHeader = to_unicode(r.getheader("cache-control"))
				cacheControlHeader = cacheControlHeader.split(u'=')[1]
				self.cache = cacheControlHeader
			except:
				pass
		
		self.allHeaders = r.getheaders()
		
	def __repr__(self):
		return u'<SSDPResponse(%(location)s, %(st)s, %(usn)s, %(server)s)>' % (self.__dict__) + to_unicode(self.allHeaders) + u'</SSDPResonse>'


#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# uPnPDiscover
#	Module-level function that executes a uPNP MSEARCH operation to find devices matching
#	a given service
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
def uPnPDiscover(service, timeout=3, retries=1):
    group = ("239.255.255.250", 1900)
    message = "\r\n".join([
        "M-SEARCH * HTTP/1.1",
        "HOST: " + group[0] + ":" + to_str(group[1]),
        "MAN: ""ssdp:discover""",
        "ST: " + service,"MX: 3","",""])
    socket.setdefaulttimeout(timeout)
    responses = {}
    for _ in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(message, group)
        while True:
            try:
                response = SSDPResponse(sock.recv(1024))
                responses[response.location] = response
            except socket.timeout:
                break
    return responses.values()
 
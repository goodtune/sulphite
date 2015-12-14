#!/usr/bin/env python

import os
import re
import sys
import time
import string
import socket


from pprint     import PrettyPrinter
from supervisor import childutils

from optparse   import OptionParser

PP = PrettyPrinter( indent = 4 )

class Sulphite(object):
    def __init__ ( self, **kwargs ):
        self.graphite_server    = kwargs.get( 'graphite_server',    'localhost' )
        self.graphite_port      = kwargs.get( 'graphite_port',      2023 )
        self.graphite_prefix    = kwargs.get( 'graphite_prefix',    None )
        self.graphite_suffix    = kwargs.get( 'graphite_suffix',    None )
        self.graphite_timeout   = kwargs.get( 'graphite_timeout',   1 )
        self.debug              = kwargs.get( 'debug',              None )
        self.stdin              = sys.stdin
        self.stdout             = sys.stdout

        # Allow customised metric path
        self.process_log        = kwargs.get(
            'process_log',
            '{process_name}_{group_name}.{event_name}')
        self.process_state      = kwargs.get(
            'process_state',
            '{process_name}_{group_name}.{from_state}.{event_name}')

        #sys.stderr.write( PP.pformat( self.__dict__ ) )
        #sys.stderr.flush()

        ### debug output
        #self._debug( PP.pformat( self.__dict__ ) )

    def run(self):
        """
        The main run loop - evaluates all incoming events and never exits
        """

        while True:
            headers, payload = childutils.listener.wait( self.stdin, self.stdout )

            ### debug output
            #self._debug( PP.pformat( [headers, payload] ) )

            event_name = headers.get( 'eventname', None )

            ### ignore TICK events
            if re.match( 'TICK', event_name ):
                self._debug( "Ignoring TICK event '%s'" % event_name )

            ### some sort of process related event - worth capturing
            elif re.match( 'PROCESS', event_name ):

                ### true for all process events:
                event_data      = self._parse_payload( payload, event_name )
                process_name    = event_data.get( 'processname', None )
                group_name      = event_data.get( 'groupname',   None )

                ### stdout/stderr capturing
                if re.match( 'PROCESS_LOG', event_name ):
                    event = self.process_log.format(
                        group_name=group_name,
                        process_name=process_name,
                        event_name=event_name.lower(),
                    )
                    self._send_to_graphite( event )

                ### state change
                elif re.match( 'PROCESS_STATE', event_name ):
                    event = self.process_state.format(
                        group_name=group_name,
                        process_name=process_name,
                        event_name=event_name.lower(),
                        from_state=event_data.get('from_state', 'unknown').lower(),
                    )
                    self._send_to_graphite( event )

                ### ignore IPC for now
                elif re.match( 'PROCESS_COMMUNICATION', event_name ):
                    self._debug( "Ignoring PROCESS event: '%s'" % event_name )

                ### unknown process event..?
                else:
                    self._debug( "Unknown PROCESS event: '%s'" % event_name )

            ### completely unknown event
            else:
                self._debug( "Unknown event: '%s'" % event_name )


            #event =

            childutils.listener.ok( self.stdout )

    def _send_to_graphite(self, event):
        """
        Take a string ready to be a graphite event and send it to the graphite host.
        """

        try:
            sock = socket.create_connection( \
                    (self.graphite_server, self.graphite_port), self.graphite_timeout )
            message = ""

            ### wrap the event with prefix/suffix, if applicable
            if self.graphite_prefix:
                message += self.graphite_prefix + '.'

            ### the event itself
            message += event

            ### the suffix
            if self.graphite_suffix:
                message += '.' + self.graphite_suffix

            ### new line is required or graphite will silently discard the metric.
            message = "%s 1 %s\n" % ( message, int(time.time()) )

            self._debug( "Sending to graphite: %s" % message )

            sock.send( message )
            sock.close()

        except socket.error, e:

            self._debug( "Could not connect to graphite for '%s': %s" % (event, e) )

    def _parse_payload( self, payload, event_name ):
        """
        Take a header string and parse it into key/values
        """

        ### payload headers can look like this, where 'foo 01' is the actual
        ### processname. So hooray for complicated parsing :(
        # 'processname:foo 01 groupname:test from_state:STARTING pid:4424'

        ### I raised an issue to make parsing easier, or to ban spaces/colons:
        ### https://github.com/Supervisor/supervisor/issues/181
        ### Spaces/colons will be deprecated going forward, so let's just
        ### deal with any problems that may arise here and document the issue.

        ### read the first line, split that on spaces, then split that on colons
        line = payload.split( "\n", 1 )
        return dict( [ x.split(':') for x in line[0].split() ] )


    def _debug( self, msg ):
        """
        Write a string to STDERR and flush the buffer
        """

        if self.debug:
            sys.stderr.write( msg + "\n" )
            sys.stderr.flush()


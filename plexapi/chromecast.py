import logging
import sys
import threading
import time

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

try:
    import pychromecast
except ImportError:
    print('pychromecast is needed')

from pychromecast.controllers import BaseController


STREAM_TYPE_UNKNOWN = 'UNKNOWN'
STREAM_TYPE_BUFFERED = 'BUFFERED'
STREAM_TYPE_LIVE = 'LIVE'
MESSAGE_TYPE = 'type'
TYPE_PLAY = 'PLAY'
TYPE_PAUSE = 'PAUSE'
TYPE_STOP = 'STOP'
TYPE_STEPFORWARD = 'STEPFORWARD'
TYPE_STEPBACKWARD = 'STEPBACK'
TYPE_PREVIOUS = 'PREVIOUS'
TYPE_NEXT = 'NEXT'
TYPE_LOAD = 'LOAD'
TYPE_DETAILS = 'SHOWDETAILS'
TYPE_SEEK = 'SEEK'
TYPE_MEDIA_STATUS = 'MEDIA_STATUS'
TYPE_GET_STATUS = 'GET_STATUS'
TYPE_EDIT_TRACKS_INFO = 'EDIT_TRACKS_INFO'


def media_to_chromecast_command(media, **kw):
    """Create the message that chromecast requires."""

    server_url = urlparse(media._server._baseurl)
    content_type = ('video/mp4') if media.TYPE in ('movie', 'episode') else ('audio/mp3')
    g = kw.get

    plq = media._server.createPlayQueue(media).playQueueID

    d = {
        'type': g('type', 'LOAD'),
        'requestId': g('requestid', 1),
        'media': {
            'contentId': media.key,
            'streamType': 'BUFFERED',
            'contentType': content_type,
            'customData': {
                'offset': g('offset', 0),
                'directPlay': g('directplay', True),
                'directStream': g('directstream', True),
                'subtitleSize': g('subtitlesize', 100),
                'audioBoost': g('audioboost', 100),
                'server': {
                    'machineIdentifier': media._server.machineIdentifier,
                    'transcoderVideo': g('transcodervideo', True),
                    'transcoderVideoRemuxOnly': g('transcodervideovemuxonly', False),
                    'transcoderAudio': g('transcoderAudio', True),
                    'version': '1.4.3.3433',  # media._server.version
                    'myPlexSubscription': media._server.myPlexSubscription,
                    'isVerifiedHostname': g('isVerifiedHostname', True),
                    'protocol': server_url.scheme,
                    'address': server_url.hostname,
                    'port': server_url.port,
                    'accessToken': media._server._token,  # Create a server.transit-token() method.
                    'user': {
                        'username': media._server.myPlexUsername
                    }
                },
                'containerKey': '/playQueues/{}?own=1&window=200'.format(plq)
            },
            'autoplay': g('autoplay', True),
            'currentTime': g('currenttime', 0)
        }
    }

    return d


class PlexController(BaseController):
    """ Controller to interact with Plex namespace. """

    def __init__(self):
        super(PlexController, self).__init__('urn:x-cast:plex', '9AC194DC')
        self.app_id = '9AC194DC'
        self.namespace = 'urn:x-cast:plex'
        self.request_id = 0
        self.play_media_event = threading.Event()

    def _send_cmd(self, msg, namespace=None, inc_session_id=False,
                  callback_function=None, inc=True):
        """Wrapper the commands."""
        self.logger.debug('Sending msg %r %s %s %s %s',
                          msg, namespace, inc_session_id, callback_function, inc)

        if inc:
            self._inc_request()

        if namespace:
            old = self.namespace
            try:
                self.namespace = namespace
                self.send_message(msg, inc_session_id=inc_session_id, callback_function=callback_function)
            finally:
                self.namespace = old
        else:
            self.send_message(msg, inc_session_id=inc_session_id,
                              callback_function=callback_function)

    def _inc_request(self):
        self.request_id += 1
        return self.request_id

    def receive_message(self, message, data):
        """ Called when a messag from plex to our controller is received.

            I havnt seen any message for ut but lets keep for for now, the
            tests i have done is minimal.
        """

        self.logger.debug('Plex media receive function called.')
        if data[MESSAGE_TYPE] == TYPE_MEDIA_STATUS:
            self.logger.debug('(PlexController) MESSAGE RECEIVED: ' + data)
            return True

        return False

    def stop(self):
        """Send stop command."""
        self._send_cmd({MESSAGE_TYPE: TYPE_STOP})

    def pause(self):
        """Send pause command."""
        self._send_cmd({MESSAGE_TYPE: TYPE_PAUSE})

    def play(self):
        """Send play command."""
        self._send_cmd({MESSAGE_TYPE: TYPE_PLAY})

    def previous(self):
        """Send previous command."""
        self._send_cmd({MESSAGE_TYPE: TYPE_PREVIOUS})

    def next(self):
        self._send_cmd({MESSAGE_TYPE: TYPE_NEXT})

    def seek(self, position, resume_state='PLAYBACK_START'):
        """Send seek command"""
        self._send_cmd({MESSAGE_TYPE: TYPE_SEEK,
                        'currentTime': position,
                        'resumeState': resume_state})

    def rewind(self):
        """Rewind back to the start"""
        self.seek(0)

    def set_volume(self, percent):
        # Feels dirty..
        self._socket_client.receiver_controller.set_volume(float(percent / 100))

    def volume_up(self, delta=0.1):
        """ Increment volume by 0.1 (or delta) unless it is already maxed.
        Returns the new volume.
        """
        if delta <= 0:
            raise ValueError(
                "volume delta must be greater than zero, not {}".format(delta))
        return self.set_volume(self.status.volume_level + delta)

    def volume_down(self, delta=0.1):
        """ Decrement the volume by 0.1 (or delta) unless it is already 0.
        Returns the new volume.
        """
        if delta <= 0:
            raise ValueError(
                "volume delta must be greater than zero, not {}".format(delta))
        return self.set_volume(self.status.volume_level - delta)

    def mute(self, status=None):
        """ mute the sound.
            status is just a override.
        """
        if status is not None:
            st = status
        else:
            st = not status.volume_muted

        self._socket_client.receiver_controller.set_volume_muted(st)

    def show_media(self, media):
        """Show the media on the screen, but don't start it."""
        msg = media_to_chromecast_command(media, type=TYPE_DETAILS, requestid=self._inc_request())

        def cb():
            self._send_cmd(msg, inc_session_id=True, inc=False)

        self.launch(cb)

    def quit_app(self):
        """Quit the plex app"""
        self._socket_client.receiver_controller.stop_app()

    @property
    def status(self):
        # So to get this we could add a listener and update the data ourself
        # or get can just use socket_clients
        # status should get a own pr so we can grab the subtitle (episode title.)
        # Lets just patch this for now..
        @property
        def episode_title(self):
            return self.media_metadata.get('subtitle')
        mc = self._socket_client.media_controller.status
        mc.episode_title = episode_title
        return mc

    def disable_subtitle(self):  # Shit does not work.
        """Disable subtitle."""
        self._send_cmd({
            MESSAGE_TYPE: TYPE_EDIT_TRACKS_INFO,
            "activeTrackIds": []
        }, namespace='urn:x-cast:com.google.cast.media')

    def _send_start_play(self, media, **kwargs):
        msg = media_to_chromecast_command(media, requestid=self._inc_request(), **kwargs)
        self._send_cmd(msg, namespace='urn:x-cast:com.google.cast.media',
                       inc_session_id=True, inc=False)

    def block_until_playing(self, item, timeout=None, **kwargs):
        """Helper just incase this is running as a script."""
        self.play_media(item)
        self.play_media_event.wait(timeout)
        self.play_media_event.clear()

    def play_media(self, item, **kwargs):
        """Start playback in the chromecast using the
           selected media.

           kwargs is passed to the load method.

        """
        # Just incase..
        self.play_media_event.clear()

        def app_launched_callback():
            try:
                self._send_start_play(item, **kwargs)
            finally:
                self.play_media_event.set()

        self.launch(app_launched_callback)

    def join(self, timeout=None):
        self._socket_client.join(timeout=timeout)

    def disconnect(self, timeout=None, blocking=True):
        self._socket_client.disconnect()
        if blocking:
            self.join(timeout=timeout)

    def step_forward(self):
        offset = self.status.adjusted_current_time + 30
        self.seek(offset)

    def step_backwards(self):
        offset = self.status.adjusted_current_time - 10
        self.seek(offset)


if __name__ == '__main__':
    """Just to show the a example usage.

        Usage: python chromecast.py devicename movie_name url token

    """
    from plexapi.server import PlexServer

    logging.basicConfig(level=logging.DEBUG)
    # Need to be python 3.4 or higher.

    """chromecast.py devicename movie_name url token"""
    devicename = sys.argv[1]
    media_name = sys.argv[2]
    url = sys.argv[3]
    token = sys.argv[4]

    chromecasts = pychromecast.get_chromecasts()
    if len(chromecasts) > 1:
        cast = next(cc for cc in chromecasts if cc.device.friendly_name == sys.argv[1])
    else:
        cast = chromecasts[0]

    # Start worker thead.
    cast.start()  # or connect manually using cast.connect()
    # Initaliize the controller
    pc = PlexController()
    # Add the controller so we can reach the the namespace changes etc.
    cast.register_handler(pc)
    cast.wait()

    pms = PlexServer(url, token)

    items = pms.search(media_name)
    item = items[0].episodes().reload()
    if len(items):
        pc.block_until_playing(item)
        # pc.play_media(item)
        # pc.show_media(items[0])
        # pc.pause()
        # etc etc
    else:
        print('Didnt find any media')

    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            break

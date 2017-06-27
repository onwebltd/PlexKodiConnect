# -*- coding: utf-8 -*-

###############################################################################
import logging
import threading

import xbmc
import xbmcgui
import xbmcaddon
from xbmcvfs import exists


from utils import window, settings, language as lang, thread_methods
import downloadutils

import PlexAPI
from PlexFunctions import GetMachineIdentifier
import state

###############################################################################

log = logging.getLogger("PLEX."+__name__)

###############################################################################


@thread_methods(add_suspends=['SUSPEND_USER_CLIENT'])
class UserClient(threading.Thread):

    # Borg - multiple instances, shared state
    __shared_state = {}

    def __init__(self, callback=None):
        self.__dict__ = self.__shared_state
        if callback is not None:
            self.mgr = callback

        self.auth = True
        self.retry = 0

        self.currUser = None
        self.currServer = None
        self.currToken = None
        self.HasAccess = True
        self.AdditionalUser = []

        self.userSettings = None

        self.addon = xbmcaddon.Addon()
        self.doUtils = downloadutils.DownloadUtils()

        threading.Thread.__init__(self)

    def getUsername(self):
        """
        Returns username as unicode
        """
        username = settings('username')
        if not username:
            log.debug("No username saved, trying to get Plex username")
            username = settings('plexLogin')
            if not username:
                log.debug("Also no Plex username found")
                return ""
        return username

    def getServer(self, prefix=True):
        # Original host
        self.servername = settings('plex_servername')
        HTTPS = settings('https') == "true"
        host = settings('ipaddress')
        port = settings('port')
        self.machineIdentifier = settings('plex_machineIdentifier')

        server = host + ":" + port

        if not host:
            log.debug("No server information saved.")
            return False

        # If https is true
        if prefix and HTTPS:
            server = "https://%s" % server
        # If https is false
        elif prefix and not HTTPS:
            server = "http://%s" % server
        # User entered IP; we need to get the machineIdentifier
        if self.machineIdentifier == '' and prefix is True:
            self.machineIdentifier = GetMachineIdentifier(server)
            if self.machineIdentifier is None:
                self.machineIdentifier = ''
            settings('plex_machineIdentifier', value=self.machineIdentifier)
        log.debug('Returning active server: %s' % server)
        return server

    def getSSLverify(self):
        # Verify host certificate
        return None if settings('sslverify') == 'true' else False

    def getSSL(self):
        # Client side certificate
        return None if settings('sslcert') == 'None' \
            else settings('sslcert')

    def setUserPref(self):
        log.debug('Setting user preferences')
        # Only try to get user avatar if there is a token
        if self.currToken:
            url = PlexAPI.PlexAPI().GetUserArtworkURL(self.currUser)
            if url:
                window('PlexUserImage', value=url)
        # Set resume point max
        # url = "{server}/emby/System/Configuration?format=json"
        # result = doUtils.downloadUrl(url)

    def hasAccess(self):
        # Plex: always return True for now
        return True

    def loadCurrUser(self, username, userId, usertoken, authenticated=False):
        log.debug('Loading current user')
        doUtils = self.doUtils

        self.currToken = usertoken
        self.currServer = self.getServer()
        self.ssl = self.getSSLverify()
        self.sslcert = self.getSSL()

        if authenticated is False:
            if self.currServer is None:
                return False
            log.debug('Testing validity of current token')
            res = PlexAPI.PlexAPI().CheckConnection(self.currServer,
                                                    token=self.currToken,
                                                    verifySSL=self.ssl)
            if res is False:
                # PMS probably offline
                return False
            elif res == 401:
                log.error('Token is no longer valid')
                return 401
            elif res >= 400:
                log.error('Answer from PMS is not as expected. Retrying')
                return False

        # Set to windows property
        state.PLEX_USER_ID = userId or None
        state.PLEX_USERNAME = username
        # This is the token for the current PMS (might also be '')
        window('pms_token', value=self.currToken)
        # This is the token for plex.tv for the current user
        # Is only '' if user is not signed in to plex.tv
        window('plex_token', value=settings('plexToken'))
        state.PLEX_TOKEN = settings('plexToken') or None
        window('plex_restricteduser', value=settings('plex_restricteduser'))
        state.RESTRICTED_USER = True \
            if settings('plex_restricteduser') == 'true' else False
        window('pms_server', value=self.currServer)
        window('plex_machineIdentifier', value=self.machineIdentifier)
        window('plex_servername', value=self.servername)
        window('plex_authenticated', value='true')
        state.AUTHENTICATED = True

        window('useDirectPaths', value='true'
               if settings('useDirectPaths') == "1" else 'false')
        state.DIRECT_PATHS = True if settings('useDirectPaths') == "1" \
            else False
        state.INDICATE_MEDIA_VERSIONS = True \
            if settings('indicate_media_versions') == "true" else False
        window('plex_force_transcode_pix', value='true'
               if settings('force_transcode_pix') == "1" else 'false')

        # Start DownloadUtils session
        doUtils.startSession(reset=True)
        # self.getAdditionalUsers()
        # Set user preferences in settings
        self.currUser = username
        self.setUserPref()

        # Writing values to settings file
        settings('username', value=username)
        settings('userid', value=userId)
        settings('accessToken', value=usertoken)
        return True

    def authenticate(self):
        log.debug('Authenticating user')
        dialog = xbmcgui.Dialog()

        # Give attempts at entering password / selecting user
        if self.retry >= 2:
            log.error("Too many retries to login.")
            state.PMS_STATUS = 'Stop'
            dialog.ok(lang(33001),
                      lang(39023))
            xbmc.executebuiltin(
                'Addon.OpenSettings(plugin.video.plexkodiconnect)')
            return False

        # Get /profile/addon_data
        addondir = xbmc.translatePath(self.addon.getAddonInfo('profile'))

        # If there's no settings.xml
        if not exists("%ssettings.xml" % addondir):
            log.error("Error, no settings.xml found.")
            self.auth = False
            return False
        server = self.getServer()
        # If there is no server we can connect to
        if not server:
            log.info("Missing server information.")
            self.auth = False
            return False

        # If there is a username in the settings, try authenticating
        username = settings('username')
        userId = settings('userid')
        usertoken = settings('accessToken')
        enforceLogin = settings('enforceUserLogin')
        # Found a user in the settings, try to authenticate
        if username and enforceLogin == 'false':
            log.debug('Trying to authenticate with old settings')
            answ = self.loadCurrUser(username,
                                     userId,
                                     usertoken,
                                     authenticated=False)
            if answ is True:
                # SUCCESS: loaded a user from the settings
                return True
            elif answ == 401:
                log.error("User token no longer valid. Sign user out")
                settings('username', value='')
                settings('userid', value='')
                settings('accessToken', value='')
            else:
                log.debug("Could not yet authenticate user")
                return False

        plx = PlexAPI.PlexAPI()

        # Could not use settings - try to get Plex user list from plex.tv
        plextoken = settings('plexToken')
        if plextoken:
            log.info("Trying to connect to plex.tv to get a user list")
            userInfo = plx.ChoosePlexHomeUser(plextoken)
            if userInfo is False:
                # FAILURE: Something went wrong, try again
                self.auth = True
                self.retry += 1
                return False
            username = userInfo['username']
            userId = userInfo['userid']
            usertoken = userInfo['token']
        else:
            log.info("Trying to authenticate without a token")
            username = ''
            userId = ''
            usertoken = ''

        if self.loadCurrUser(username, userId, usertoken, authenticated=False):
            # SUCCESS: loaded a user from the settings
            return True
        else:
            # FAILUR: Something went wrong, try again
            self.auth = True
            self.retry += 1
            return False

    def resetClient(self):
        log.debug("Reset UserClient authentication.")
        self.doUtils.stopSession()

        window('plex_authenticated', clear=True)
        state.AUTHENTICATED = False
        window('pms_token', clear=True)
        state.PLEX_TOKEN = None
        window('plex_token', clear=True)
        window('pms_server', clear=True)
        window('plex_machineIdentifier', clear=True)
        window('plex_servername', clear=True)
        state.PLEX_USER_ID = None
        state.PLEX_USERNAME = None
        window('plex_restricteduser', clear=True)
        state.RESTRICTED_USER = False

        settings('username', value='')
        settings('userid', value='')
        settings('accessToken', value='')

        # Reset token in downloads
        self.doUtils.setToken('')

        self.currToken = None
        self.auth = True
        self.currUser = None

        self.retry = 0

    def run(self):
        log.info("----===## Starting UserClient ##===----")
        thread_stopped = self.thread_stopped
        thread_suspended = self.thread_suspended
        while not thread_stopped():
            while thread_suspended():
                if thread_stopped():
                    break
                xbmc.sleep(1000)

            if state.PMS_STATUS == "Stop":
                xbmc.sleep(500)
                continue

            # Verify the connection status to server
            elif state.PMS_STATUS == "restricted":
                # Parental control is restricting access
                self.HasAccess = False

            elif state.PMS_STATUS == "401":
                # Unauthorized access, revoke token
                state.PMS_STATUS = 'Auth'
                window('plex_serverStatus', value='Auth')
                self.resetClient()
                xbmc.sleep(3000)

            if self.auth and (self.currUser is None):
                # Try to authenticate user
                if not state.PMS_STATUS or state.PMS_STATUS == "Auth":
                    # Set auth flag because we no longer need
                    # to authenticate the user
                    self.auth = False
                    if self.authenticate():
                        # Successfully authenticated and loaded a user
                        log.info("Successfully authenticated!")
                        log.info("Current user: %s" % self.currUser)
                        log.info("Current userId: %s" % state.PLEX_USER_ID)
                        self.retry = 0
                        state.SUSPEND_LIBRARY_THREAD = False
                        window('plex_serverStatus', clear=True)
                        state.PMS_STATUS = False

            if not self.auth and (self.currUser is None):
                # Loop if no server found
                server = self.getServer()

                # The status Stop is for when user cancelled password dialog.
                # Or retried too many times
                if server and state.PMS_STATUS != "Stop":
                    # Only if there's information found to login
                    log.debug("Server found: %s" % server)
                    self.auth = True

            # Minimize CPU load
            xbmc.sleep(100)

        log.info("##===---- UserClient Stopped ----===##")

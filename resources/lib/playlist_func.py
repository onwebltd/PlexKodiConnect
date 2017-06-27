import logging
from urllib import quote
from urlparse import parse_qsl, urlsplit
from re import compile as re_compile

import plexdb_functions as plexdb
from downloadutils import DownloadUtils as DU
from utils import JSONRPC, tryEncode, escape_html
from PlexAPI import API
from PlexFunctions import GetPlexMetadata

###############################################################################

log = logging.getLogger("PLEX."+__name__)

REGEX = re_compile(r'''metadata%2F(\d+)''')
###############################################################################

# kodi_item dict:
# {u'type': u'movie', u'id': 3, 'file': path-to-file}


class Playlist_Object_Baseclase(object):
    playlistid = None     # Kodi playlist ID, [int]
    type = None           # Kodi type: 'audio', 'video', 'picture'
    kodi_pl = None        # Kodi xbmc.PlayList object
    items = []            # list of PLAYLIST_ITEMS
    old_kodi_pl = []      # to store old Kodi JSON result with all pl items
    ID = None             # Plex id, e.g. playQueueID
    version = None        # Plex version, [int]
    selectedItemID = None
    selectedItemOffset = None
    shuffled = 0          # [int], 0: not shuffled, 1: ??? 2: ???
    repeat = 0            # [int], 0: not repeated, 1: ??? 2: ???
    # If Companion playback is initiated by another user
    plex_transient_token = None

    def __repr__(self):
        answ = "<%s: " % (self.__class__.__name__)
        # For some reason, can't use dir directly
        answ += "ID: %s, " % self.ID
        answ += "items: %s, " % self.items
        for key in self.__dict__:
            if key not in ("ID", 'items'):
                if type(getattr(self, key)) in (str, unicode):
                    answ += '%s: %s, ' % (key, tryEncode(getattr(self, key)))
                else:
                    # e.g. int
                    answ += '%s: %s, ' % (key, str(getattr(self, key)))
        return answ[:-2] + ">"

    def clear(self):
        """
        Resets the playlist object to an empty playlist
        """
        # Clear Kodi playlist object
        self.kodi_pl.clear()
        self.items = []
        self.old_kodi_pl = []
        self.ID = None
        self.version = None
        self.selectedItemID = None
        self.selectedItemOffset = None
        self.shuffled = 0
        self.repeat = 0
        self.plex_transient_token = None
        log.debug('Playlist cleared: %s' % self)


class Playlist_Object(Playlist_Object_Baseclase):
    kind = 'playList'


class Playqueue_Object(Playlist_Object_Baseclase):
    kind = 'playQueue'


class Playlist_Item(object):
    ID = None               # Plex playlist/playqueue id, e.g. playQueueItemID
    plex_id = None          # Plex unique item id, "ratingKey"
    plex_type = None        # Plex type, e.g. 'movie', 'clip'
    plex_UUID = None        # Plex librarySectionUUID
    kodi_id = None          # Kodi unique kodi id (unique only within type!)
    kodi_type = None        # Kodi type: 'movie'
    file = None             # Path to the item's file. STRING!!
    uri = None              # Weird Plex uri path involving plex_UUID. STRING!
    guid = None             # Weird Plex guid

    def __repr__(self):
        answ = "<%s: " % (self.__class__.__name__)
        for key in self.__dict__:
            if type(getattr(self, key)) in (str, unicode):
                answ += '%s: %s, ' % (key, tryEncode(getattr(self, key)))
            else:
                # e.g. int
                answ += '%s: %s, ' % (key, str(getattr(self, key)))
        return answ[:-2] + ">"


def playlist_item_from_kodi(kodi_item):
    """
    Turns the JSON answer from Kodi into a playlist element

    Supply with data['item'] as returned from Kodi JSON-RPC interface.
    kodi_item dict contains keys 'id', 'type', 'file' (if applicable)
    """
    item = Playlist_Item()
    item.kodi_id = kodi_item.get('id')
    item.kodi_type = kodi_item.get('type')
    if item.kodi_id:
        with plexdb.Get_Plex_DB() as plex_db:
            plex_dbitem = plex_db.getItem_byKodiId(kodi_item['id'],
                                                   kodi_item['type'])
        try:
            item.plex_id = plex_dbitem[0]
            item.plex_type = plex_dbitem[2]
            item.plex_UUID = plex_dbitem[0]     # we dont need the uuid yet :-)
        except TypeError:
            pass
    item.file = kodi_item.get('file')
    if item.plex_id is None and item.file is not None:
        query = dict(parse_qsl(urlsplit(item.file).query))
        item.plex_id = query.get('plex_id')
        item.plex_type = query.get('itemType')
    if item.plex_id is None:
        item.uri = 'library://whatever/item/%s' % quote(item.file, safe='')
    else:
        # TO BE VERIFIED - PLEX DOESN'T LIKE PLAYLIST ADDS IN THIS MANNER
        item.uri = ('library://%s/item/library%%2Fmetadata%%2F%s' %
                    (item.plex_UUID, item.plex_id))
    log.debug('Made playlist item from Kodi: %s' % item)
    return item


def playlist_item_from_plex(plex_id):
    """
    Returns a playlist element providing the plex_id ("ratingKey")

    Returns a Playlist_Item
    """
    item = Playlist_Item()
    item.plex_id = plex_id
    with plexdb.Get_Plex_DB() as plex_db:
        plex_dbitem = plex_db.getItem_byId(plex_id)
    try:
        item.plex_type = plex_dbitem[5]
        item.kodi_id = plex_dbitem[0]
        item.kodi_type = plex_dbitem[4]
    except:
        raise KeyError('Could not find plex_id %s in database' % plex_id)
    item.plex_UUID = plex_id
    item.uri = ('library://%s/item/library%%2Fmetadata%%2F%s' %
                (item.plex_UUID, plex_id))
    log.debug('Made playlist item from plex: %s' % item)
    return item


def playlist_item_from_xml(playlist, xml_video_element):
    """
    Returns a playlist element for the playqueue using the Plex xml
    """
    item = Playlist_Item()
    api = API(xml_video_element)
    item.plex_id = api.getRatingKey()
    item.plex_type = api.getType()
    item.ID = xml_video_element.attrib['%sItemID' % playlist.kind]
    item.guid = xml_video_element.attrib.get('guid')
    if item.guid is not None:
        item.guid = escape_html(item.guid)
    if item.plex_id:
        with plexdb.Get_Plex_DB() as plex_db:
            db_element = plex_db.getItem_byId(item.plex_id)
        try:
            item.kodi_id, item.kodi_type = int(db_element[0]), db_element[4]
        except TypeError:
            pass
    log.debug('Created new playlist item from xml: %s' % item)
    return item


def _get_playListVersion_from_xml(playlist, xml):
    """
    Takes a PMS xml as input to overwrite the playlist version (e.g. Plex
    playQueueVersion). Returns True if successful, False otherwise
    """
    try:
        playlist.version = int(xml.attrib['%sVersion' % playlist.kind])
    except (TypeError, AttributeError, KeyError):
        log.error('Could not get new playlist Version for playlist %s'
                  % playlist)
        return False
    return True


def get_playlist_details_from_xml(playlist, xml):
    """
    Takes a PMS xml as input and overwrites all the playlist's details, e.g.
    playlist.ID with the XML's playQueueID
    """
    try:
        playlist.ID = xml.attrib['%sID' % playlist.kind]
        playlist.version = xml.attrib['%sVersion' % playlist.kind]
        playlist.shuffled = xml.attrib['%sShuffled' % playlist.kind]
        playlist.selectedItemID = xml.attrib.get(
            '%sSelectedItemID' % playlist.kind)
        playlist.selectedItemOffset = xml.attrib.get(
            '%sSelectedItemOffset' % playlist.kind)
    except:
        log.error('Could not parse xml answer from PMS for playlist %s'
                  % playlist)
        import traceback
        log.error(traceback.format_exc())
        raise KeyError
    log.debug('Updated playlist from xml: %s' % playlist)


def update_playlist_from_PMS(playlist, playlist_id=None, xml=None):
    """
    Updates Kodi playlist using a new PMS playlist. Pass in playlist_id if we
    need to fetch a new playqueue

    If an xml is passed in, the playlist will be overwritten with its info
    """
    if xml is None:
        xml = get_PMS_playlist(playlist, playlist_id)
    # Clear our existing playlist and the associated Kodi playlist
    playlist.clear()
    # Set new values
    try:
        get_playlist_details_from_xml(playlist, xml)
    except KeyError:
        log.error('Could not update playlist from PMS')
        return
    for plex_item in xml:
        playlist_item = add_to_Kodi_playlist(playlist, plex_item)
        if playlist_item is not None:
            playlist.items.append(playlist_item)


def init_Plex_playlist(playlist, plex_id=None, kodi_item=None):
    """
    Initializes the Plex side without changing the Kodi playlists

    WILL ALSO UPDATE OUR PLAYLISTS
    """
    log.debug('Initializing the playlist %s on the Plex side' % playlist)
    try:
        if plex_id:
            item = playlist_item_from_plex(plex_id)
        else:
            item = playlist_item_from_kodi(kodi_item)
        params = {
            'next': 0,
            'type': playlist.type,
            'uri': item.uri
        }
        xml = DU().downloadUrl(url="{server}/%ss" % playlist.kind,
                               action_type="POST",
                               parameters=params)
        get_playlist_details_from_xml(playlist, xml)
    except KeyError:
        log.error('Could not init Plex playlist')
        return
    playlist.items.append(item)
    log.debug('Initialized the playlist on the Plex side: %s' % playlist)


def add_listitem_to_playlist(playlist, pos, listitem, kodi_id=None,
                             kodi_type=None, plex_id=None, file=None):
    """
    Adds a listitem to both the Kodi and Plex playlist at position pos [int].

    If file is not None, file will overrule kodi_id!

    file: str!!
    """
    log.debug('add_listitem_to_playlist at position %s. Playlist before add: '
              '%s' % (pos, playlist))
    kodi_item = {'id': kodi_id, 'type': kodi_type, 'file': file}
    if playlist.ID is None:
        init_Plex_playlist(playlist, plex_id, kodi_item)
    else:
        add_item_to_PMS_playlist(playlist, pos, plex_id, kodi_item)
    if kodi_id is None and playlist.items[pos].kodi_id:
        kodi_id = playlist.items[pos].kodi_id
        kodi_type = playlist.items[pos].kodi_type
    if file is None:
        file = playlist.items[pos].file
    # Otherwise we double the item!
    del playlist.items[pos]
    kodi_item = {'id': kodi_id, 'type': kodi_type, 'file': file}
    add_listitem_to_Kodi_playlist(playlist,
                                  pos,
                                  listitem,
                                  file,
                                  kodi_item=kodi_item)


def add_item_to_playlist(playlist, pos, kodi_id=None, kodi_type=None,
                         plex_id=None, file=None):
    """
    Adds an item to BOTH the Kodi and Plex playlist at position pos [int]

    file: str!
    """
    log.debug('add_item_to_playlist. Playlist before adding: %s' % playlist)
    kodi_item = {'id': kodi_id, 'type': kodi_type, 'file': file}
    if playlist.ID is None:
        init_Plex_playlist(playlist, plex_id, kodi_item)
    else:
        add_item_to_PMS_playlist(playlist, pos, plex_id, kodi_item)
    kodi_id = playlist.items[pos].kodi_id
    kodi_type = playlist.items[pos].kodi_type
    file = playlist.items[pos].file
    add_item_to_kodi_playlist(playlist, pos, kodi_id, kodi_type, file)


def add_item_to_PMS_playlist(playlist, pos, plex_id=None, kodi_item=None):
    """
    Adds a new item to the playlist at position pos [int] only on the Plex
    side of things (e.g. because the user changed the Kodi side)

    WILL ALSO UPDATE OUR PLAYLISTS
    """
    if plex_id:
        try:
            item = playlist_item_from_plex(plex_id)
        except KeyError:
            log.error('Could not add new item to the PMS playlist')
            return
    else:
        item = playlist_item_from_kodi(kodi_item)
    url = "{server}/%ss/%s?uri=%s" % (playlist.kind, playlist.ID, item.uri)
    # Will always put the new item at the end of the Plex playlist
    xml = DU().downloadUrl(url, action_type="PUT")
    try:
        item.ID = xml[-1].attrib['%sItemID' % playlist.kind]
    except IndexError:
        log.info('Could not get playlist children. Adding a dummy')
    except (TypeError, AttributeError, KeyError):
        log.error('Could not add item %s to playlist %s'
                  % (kodi_item, playlist))
        return
    # Get the guid for this item
    for plex_item in xml:
        if plex_item.attrib['%sItemID' % playlist.kind] == item.ID:
            item.guid = escape_html(plex_item.attrib['guid'])
    playlist.items.append(item)
    if pos == len(playlist.items) - 1:
        # Item was added at the end
        _get_playListVersion_from_xml(playlist, xml)
    else:
        # Move the new item to the correct position
        move_playlist_item(playlist,
                           len(playlist.items) - 1,
                           pos)
    log.debug('Successfully added item on the Plex side: %s' % playlist)


def add_item_to_kodi_playlist(playlist, pos, kodi_id=None, kodi_type=None,
                              file=None):
    """
    Adds an item to the KODI playlist only. WILL ALSO UPDATE OUR PLAYLISTS

    Returns False if unsuccessful

    file: str!
    """
    log.debug('Adding new item kodi_id: %s, kodi_type: %s, file: %s to Kodi '
              'only at position %s for %s'
              % (kodi_id, kodi_type, file, pos, playlist))
    params = {
        'playlistid': playlist.playlistid,
        'position': pos
    }
    if kodi_id is not None:
        params['item'] = {'%sid' % kodi_type: int(kodi_id)}
    else:
        params['item'] = {'file': file}
    reply = JSONRPC('Playlist.Insert').execute(params)
    if reply.get('error') is not None:
        log.error('Could not add item to playlist. Kodi reply. %s' % reply)
        return False
    else:
        playlist.items.insert(pos, playlist_item_from_kodi(
            {'id': kodi_id, 'type': kodi_type, 'file': file}))
        return True


def move_playlist_item(playlist, before_pos, after_pos):
    """
    Moves playlist item from before_pos [int] to after_pos [int] for Plex only.

    WILL ALSO CHANGE OUR PLAYLISTS. Returns True if successful
    """
    log.debug('Moving item from %s to %s on the Plex side for %s'
              % (before_pos, after_pos, playlist))
    if after_pos == 0:
        url = "{server}/%ss/%s/items/%s/move?after=0" % \
              (playlist.kind,
               playlist.ID,
               playlist.items[before_pos].ID)
    else:
        url = "{server}/%ss/%s/items/%s/move?after=%s" % \
              (playlist.kind,
               playlist.ID,
               playlist.items[before_pos].ID,
               playlist.items[after_pos - 1].ID)
    # We need to increment the playlistVersion
    if _get_playListVersion_from_xml(
            playlist, DU().downloadUrl(url, action_type="PUT")) is False:
        return False
    # Move our item's position in our internal playlist
    playlist.items.insert(after_pos, playlist.items.pop(before_pos))
    log.debug('Done moving for %s' % playlist)
    return True


def get_PMS_playlist(playlist, playlist_id=None):
    """
    Fetches the PMS playlist/playqueue as an XML. Pass in playlist_id if we
    need to fetch a new playlist

    Returns None if something went wrong
    """
    playlist_id = playlist_id if playlist_id else playlist.ID
    xml = DU().downloadUrl(
        "{server}/%ss/%s" % (playlist.kind, playlist_id),
        headerOptions={'Accept': 'application/xml'})
    try:
        xml.attrib['%sID' % playlist.kind]
    except (AttributeError, KeyError):
        xml = None
    return xml


def refresh_playlist_from_PMS(playlist):
    """
    Only updates the selected item from the PMS side (e.g.
    playQueueSelectedItemID). Will NOT check whether items still make sense.
    """
    xml = get_PMS_playlist(playlist)
    try:
        get_playlist_details_from_xml(playlist, xml)
    except KeyError:
        log.error('Could not refresh playlist from PMS')


def delete_playlist_item_from_PMS(playlist, pos):
    """
    Delete the item at position pos [int] on the Plex side and our playlists
    """
    log.debug('Deleting position %s for %s on the Plex side' % (pos, playlist))
    xml = DU().downloadUrl("{server}/%ss/%s/items/%s?repeat=%s" %
                           (playlist.kind,
                            playlist.ID,
                            playlist.items[pos].ID,
                            playlist.repeat),
                           action_type="DELETE")
    _get_playListVersion_from_xml(playlist, xml)
    del playlist.items[pos]


def get_kodi_playlist_items(playlist):
    """
    Returns a list of the current Kodi playlist items using JSON

    E.g.:
    [{u'title': u'3 Idiots', u'type': u'movie', u'id': 3, u'file':
    u'smb://nas/PlexMovies/3 Idiots 2009 pt1.mkv', u'label': u'3 Idiots'}]
    """
    answ = JSONRPC('Playlist.GetItems').execute({
        'playlistid': playlist.playlistid,
        'properties': ["title", "file"]
    })
    try:
        answ = answ['result']['items']
    except KeyError:
        answ = []
    return answ


def get_kodi_playqueues():
    """
    Example return: [{u'playlistid': 0, u'type': u'audio'},
                     {u'playlistid': 1, u'type': u'video'},
                     {u'playlistid': 2, u'type': u'picture'}]
    """
    queues = JSONRPC('Playlist.GetPlaylists').execute()
    try:
        queues = queues['result']
    except KeyError:
        log.error('Could not get Kodi playqueues. JSON Result was: %s'
                  % queues)
        queues = []
    return queues


# Functions operating on the Kodi playlist objects ##########

def add_to_Kodi_playlist(playlist, xml_video_element):
    """
    Adds a new item to the Kodi playlist via JSON (at the end of the playlist).
    Pass in the PMS xml's video element (one level underneath MediaContainer).

    Returns a Playlist_Item or None if it did not work
    """
    item = playlist_item_from_xml(playlist, xml_video_element)
    params = {
        'playlistid': playlist.playlistid
    }
    if item.kodi_id:
        params['item'] = {'%sid' % item.kodi_type: item.kodi_id}
    else:
        params['item'] = {'file': item.file}
    reply = JSONRPC('Playlist.Add').execute(params)
    if reply.get('error') is not None:
        log.error('Could not add item %s to Kodi playlist. Error: %s'
                  % (xml_video_element, reply))
        return None
    else:
        return item


def add_listitem_to_Kodi_playlist(playlist, pos, listitem, file,
                                  xml_video_element=None, kodi_item=None):
    """
    Adds an xbmc listitem to the Kodi playlist.xml_video_element

    WILL NOT UPDATE THE PLEX SIDE, BUT WILL UPDATE OUR PLAYLISTS

    file: string!
    """
    log.debug('Insert listitem at position %s for Kodi only for %s'
              % (pos, playlist))
    # Add the item into Kodi playlist
    playlist.kodi_pl.add(file, listitem, index=pos)
    # We need to add this to our internal queue as well
    if xml_video_element is not None:
        item = playlist_item_from_xml(playlist, xml_video_element)
    else:
        item = playlist_item_from_kodi(kodi_item)
    if file is not None:
        item.file = file
    playlist.items.insert(pos, item)
    log.debug('Done inserting for %s' % playlist)


def remove_from_Kodi_playlist(playlist, pos):
    """
    Removes the item at position pos from the Kodi playlist using JSON.

    WILL NOT UPDATE THE PLEX SIDE, BUT WILL UPDATE OUR PLAYLISTS
    """
    log.debug('Removing position %s from Kodi only from %s' % (pos, playlist))
    reply = JSONRPC('Playlist.Remove').execute({
        'playlistid': playlist.playlistid,
        'position': pos
    })
    if reply.get('error') is not None:
        log.error('Could not delete the item from the playlist. Error: %s'
                  % reply)
        return
    else:
        try:
            del playlist.items[pos]
        except IndexError:
            log.error('Cannot delete position %s for %s' % (pos, playlist))


def get_pms_playqueue(playqueue_id):
    """
    Returns the Plex playqueue as an etree XML or None if unsuccessful
    """
    xml = DU().downloadUrl(
        "{server}/playQueues/%s" % playqueue_id,
        headerOptions={'Accept': 'application/xml'})
    try:
        xml.attrib
    except AttributeError:
        log.error('Could not download Plex playqueue %s' % playqueue_id)
        xml = None
    return xml


def get_plextype_from_xml(xml):
    """
    Needed if PMS returns an empty playqueue. Will get the Plex type from the
    empty playlist playQueueSourceURI. Feed with (empty) etree xml

    returns None if unsuccessful
    """
    try:
        plex_id = REGEX.findall(xml.attrib['playQueueSourceURI'])[0]
    except IndexError:
        log.error('Could not get plex_id from xml: %s' % xml.attrib)
        return
    new_xml = GetPlexMetadata(plex_id)
    try:
        new_xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        log.error('Could not get plex metadata for plex id %s' % plex_id)
        return
    return new_xml[0].attrib.get('type')

# -*- coding: utf-8 -*-

###############################################################################

from utils import kodiSQL
import logging
import variables as v

###############################################################################

log = logging.getLogger("PLEX."+__name__)

###############################################################################


class Get_Plex_DB():
    """
    Usage: with Get_Plex_DB() as plex_db:
               plex_db.do_something()

    On exiting "with" (no matter what), commits get automatically committed
    and the db gets closed
    """
    def __enter__(self):
        self.plexconn = kodiSQL('plex')
        return Plex_DB_Functions(self.plexconn.cursor())

    def __exit__(self, type, value, traceback):
        self.plexconn.commit()
        self.plexconn.close()


class Plex_DB_Functions():

    def __init__(self, plexcursor):
        self.plexcursor = plexcursor

    def getViews(self):
        """
        Returns a list of view_id
        """
        views = []
        query = '''
            SELECT view_id
            FROM view
        '''
        self.plexcursor.execute(query)
        rows = self.plexcursor.fetchall()
        for row in rows:
            views.append(row[0])
        return views

    def getAllViewInfo(self):
        """
        Returns a list of dicts for all Plex libraries:
        {
            'id': view_id,
            'name': view_name,
            'itemtype': kodi_type
            'kodi_tagid'
            'sync_to_kodi'
        }
        """
        plexcursor = self.plexcursor
        views = []
        query = '''SELECT * FROM view'''
        plexcursor.execute(query)
        rows = plexcursor.fetchall()
        for row in rows:
            views.append({'id': row[0],
                          'name': row[1],
                          'itemtype': row[2],
                          'kodi_tagid': row[3],
                          'sync_to_kodi': row[4]})
        return views

    def getView_byId(self, view_id):
        """
        Returns tuple (view_name, kodi_type, kodi_tagid) for view_id
        """
        query = '''
            SELECT view_name, kodi_type, kodi_tagid
            FROM view
            WHERE view_id = ?
        '''
        self.plexcursor.execute(query, (view_id,))
        view = self.plexcursor.fetchone()
        return view

    def getView_byType(self, kodi_type):
        """
        Returns a list of dicts for kodi_type:
            {'id': view_id, 'name': view_name, 'itemtype': kodi_type}
        """
        views = []
        query = '''
            SELECT view_id, view_name, kodi_type
            FROM view
            WHERE kodi_type = ?
        '''
        self.plexcursor.execute(query, (kodi_type,))
        rows = self.plexcursor.fetchall()
        for row in rows:
            views.append({
                'id': row[0],
                'name': row[1],
                'itemtype': row[2]
            })
        return views

    def getView_byName(self, view_name):
        """
        Returns the view_id for view_name (or None)
        """
        query = '''
            SELECT view_id
            FROM view
            WHERE view_name = ?
        '''
        self.plexcursor.execute(query, (view_name,))
        try:
            view = self.plexcursor.fetchone()[0]
        except TypeError:
            view = None
        return view

    def addView(self, view_id, view_name, kodi_type, kodi_tagid, sync=True):
        """
        Appends an entry to the view table

        sync=False: Plex library won't be synced to Kodi
        """
        query = '''
            INSERT INTO view(
                view_id, view_name, kodi_type, kodi_tagid, sync_to_kodi)
            VALUES (?, ?, ?, ?, ?)
            '''
        self.plexcursor.execute(query,
                                (view_id,
                                 view_name,
                                 kodi_type,
                                 kodi_tagid,
                                 1 if sync is True else 0))

    def updateView(self, view_name, kodi_tagid, view_id):
        """
        Updates the view_id with view_name and kodi_tagid
        """
        query = '''
            UPDATE view
            SET view_name = ?, kodi_tagid = ?
            WHERE view_id = ?
        '''
        self.plexcursor.execute(query, (view_name, kodi_tagid, view_id))

    def removeView(self, view_id):
        query = '''
            DELETE FROM view
            WHERE view_id = ?
        '''
        self.plexcursor.execute(query, (view_id,))

    def get_items_by_viewid(self, view_id):
        """
        Returns a list for view_id with one item like this:
        {
            'plex_id': xxx
            'kodi_type': xxx
        }
        """
        query = '''SELECT plex_id, kodi_type FROM plex WHERE view_id = ?'''
        self.plexcursor.execute(query, (view_id, ))
        rows = self.plexcursor.fetchall()
        res = []
        for row in rows:
            res.append({'plex_id': row[0], 'kodi_type': row[1]})
        return res

    def getItem_byFileId(self, kodi_fileid, kodi_type):
        """
        Returns plex_id for kodi_fileid and kodi_type

        None if not found
        """
        query = '''
            SELECT plex_id
            FROM plex
            WHERE kodi_fileid = ? AND kodi_type = ?
        '''
        try:
            self.plexcursor.execute(query, (kodi_fileid, kodi_type))
            item = self.plexcursor.fetchone()[0]
            return item
        except:
            return None

    def getMusicItem_byFileId(self, kodi_id, kodi_type):
        """
        Returns the plex_id for kodi_id and kodi_type

        None if not found
        """
        query = '''
            SELECT plex_id
            FROM plex
            WHERE kodi_id = ? AND kodi_type = ?
        '''
        try:
            self.plexcursor.execute(query, (kodi_id, kodi_type))
            item = self.plexcursor.fetchone()[0]
            return item
        except:
            return None

    def getItem_byId(self, plex_id):
        """
        For plex_id, returns the tuple
          (kodi_id, kodi_fileid, kodi_pathid, parent_id, kodi_type, plex_type)

        None if not found
        """
        query = '''
            SELECT kodi_id, kodi_fileid, kodi_pathid,
                parent_id, kodi_type, plex_type
            FROM plex
            WHERE plex_id = ?
        '''
        try:
            self.plexcursor.execute(query, (plex_id,))
            item = self.plexcursor.fetchone()
            return item
        except:
            return None

    def getItem_byWildId(self, plex_id):
        """
        Returns a list of tuples (kodi_id, kodi_type) for plex_id (% appended)
        """
        query = '''
            SELECT kodi_id, kodi_type
            FROM plex
            WHERE plex_id LIKE ?
        '''
        self.plexcursor.execute(query, (plex_id+"%",))
        return self.plexcursor.fetchall()

    def getItem_byView(self, view_id):
        """
        Returns kodi_id for view_id
        """
        query = '''
            SELECT kodi_id
            FROM plex
            WHERE view_id = ?
        '''
        self.plexcursor.execute(query, (view_id,))
        return self.plexcursor.fetchall()

    def getItem_byKodiId(self, kodi_id, kodi_type):
        """
        Returns the tuple (plex_id, parent_id, plex_type) for kodi_id and
        kodi_type
        """
        query = '''
            SELECT plex_id, parent_id, plex_type
            FROM plex
            WHERE kodi_id = ?
            AND kodi_type = ?
        '''
        self.plexcursor.execute(query, (kodi_id, kodi_type,))
        return self.plexcursor.fetchone()

    def getItem_byParentId(self, parent_id, kodi_type):
        """
        Returns the tuple (plex_id, kodi_id, kodi_fileid) for parent_id,
        kodi_type
        """
        query = '''
            SELECT plex_id, kodi_id, kodi_fileid
            FROM plex
            WHERE parent_id = ?
            AND kodi_type = ?"
        '''
        self.plexcursor.execute(query, (parent_id, kodi_type,))
        return self.plexcursor.fetchall()

    def getItemId_byParentId(self, parent_id, kodi_type):
        """
        Returns the tuple (plex_id, kodi_id) for parent_id, kodi_type
        """
        query = '''
            SELECT plex_id, kodi_id
            FROM plex
            WHERE parent_id = ?
            AND kodi_type = ?
        '''
        self.plexcursor.execute(query, (parent_id, kodi_type,))
        return self.plexcursor.fetchall()

    def getChecksum(self, plex_type):
        """
        Returns a list of tuples (plex_id, checksum) for plex_type
        """
        query = '''
            SELECT plex_id, checksum
            FROM plex
            WHERE plex_type = ?
        '''
        self.plexcursor.execute(query, (plex_type,))
        return self.plexcursor.fetchall()

    def getMediaType_byId(self, plex_id):
        """
        Returns plex_type for plex_id

        Or None if not found
        """
        query = '''
            SELECT plex_type
            FROM plex
            WHERE plex_id = ?
        '''
        self.plexcursor.execute(query, (plex_id,))
        try:
            itemtype = self.plexcursor.fetchone()[0]
        except TypeError:
            itemtype = None
        return itemtype

    def addReference(self, plex_id, plex_type, kodi_id, kodi_type,
                     kodi_fileid=None, kodi_pathid=None, parent_id=None,
                     checksum=None, view_id=None):
        """
        Appends or replaces an entry into the plex table
        """
        query = '''
            INSERT OR REPLACE INTO plex(
                plex_id, kodi_id, kodi_fileid, kodi_pathid, plex_type,
                kodi_type, parent_id, checksum, view_id, fanart_synced)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
        self.plexcursor.execute(query, (plex_id, kodi_id, kodi_fileid,
                                        kodi_pathid, plex_type, kodi_type,
                                        parent_id, checksum, view_id, 0))

    def updateReference(self, plex_id, checksum):
        """
        Updates checksum for plex_id
        """
        query = "UPDATE plex SET checksum = ? WHERE plex_id = ?"
        self.plexcursor.execute(query, (checksum, plex_id))

    def updateParentId(self, plexid, parent_kodiid):
        """
        Updates parent_id for plex_id
        """
        query = "UPDATE plex SET parent_id = ? WHERE plex_id = ?"
        self.plexcursor.execute(query, (parent_kodiid, plexid))

    def removeItems_byParentId(self, parent_id, kodi_type):
        """
        Removes all entries with parent_id and kodi_type
        """
        query = '''
            DELETE FROM plex
            WHERE parent_id = ?
            AND kodi_type = ?
        '''
        self.plexcursor.execute(query, (parent_id, kodi_type,))

    def removeItem_byKodiId(self, kodi_id, kodi_type):
        """
        Removes the one entry with kodi_id and kodi_type
        """
        query = '''
            DELETE FROM plex
            WHERE kodi_id = ?
            AND kodi_type = ?
        '''
        self.plexcursor.execute(query, (kodi_id, kodi_type,))

    def removeItem(self, plex_id):
        """
        Removes the one entry with plex_id
        """
        query = "DELETE FROM plex WHERE plex_id = ?"
        self.plexcursor.execute(query, (plex_id,))

    def removeWildItem(self, plex_id):
        """
        Removes all entries with plex_id with % added
        """
        query = "DELETE FROM plex WHERE plex_id LIKE ?"
        self.plexcursor.execute(query, (plex_id+"%",))

    def itemsByType(self, plex_type):
        """
        Returns a list of dicts for plex_type:
        {
            'plex_id': plex_id
            'kodiId': kodi_id
            'kodi_type': kodi_type
            'plex_type': plex_type
        }
        """
        query = '''
            SELECT plex_id, kodi_id, kodi_type
            FROM plex
            WHERE plex_type = ?
        '''
        self.plexcursor.execute(query, (plex_type, ))
        result = []
        for row in self.plexcursor.fetchall():
            result.append({
                'plex_id': row[0],
                'kodiId': row[1],
                'kodi_type': row[2],
                'plex_type': plex_type
            })
        return result

    def set_fanart_synched(self, plex_id):
        """
        Sets the fanart_synced flag to 1 for plex_id
        """
        query = '''UPDATE plex SET fanart_synced = 1 WHERE plex_id = ?'''
        self.plexcursor.execute(query, (plex_id,))

    def get_missing_fanart(self):
        """
        Returns a list of {'plex_id': x, 'plex_type': y} where fanart_synced
        flag is set to 0

        This only for plex_type is either movie or TV show
        """
        query = '''
            SELECT plex_id, plex_type FROM plex
            WHERE fanart_synced = ?
            AND (plex_type = ? OR plex_type = ?)
        '''
        self.plexcursor.execute(query,
                                (0, v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW))
        rows = self.plexcursor.fetchall()
        result = []
        for row in rows:
            result.append({'plex_id': row[0],
                           'plex_type': row[1]})
        return result

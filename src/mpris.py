import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

MPRIS_XML = """
<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="CanControl" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
  </interface>
</node>
"""

class MPRISService:
    def __init__(self, window):
        self.window = window
        self.node_info = Gio.DBusNodeInfo.new_for_xml(MPRIS_XML)
        self.owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            "org.mpris.MediaPlayer2.JustCD",
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            None
        )

    def _on_bus_acquired(self, connection, name):
        self.connection = connection
        for iface in self.node_info.interfaces:
            connection.register_object(
                "/org/mpris/MediaPlayer2",
                iface,
                self._handle_method_call,
                self._handle_get_property,
                None
            )

    def _handle_method_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "PlayPause":
            GLib.idle_add(self.window._on_play_pause_clicked, None)
        elif method == "Play":
            GLib.idle_add(self.window._on_play_pause_clicked, None)
        elif method == "Pause":
            GLib.idle_add(self.window._on_play_pause_clicked, None)
        elif method == "Stop":
            GLib.idle_add(self.window._on_stop_clicked, None)
        elif method == "Next":
            GLib.idle_add(self.window._on_next_clicked, None)
        elif method == "Previous":
            GLib.idle_add(self.window._on_prev_clicked, None)
        elif method == "Raise":
            GLib.idle_add(self.window.present)
        invocation.return_value(None)

    def _handle_get_property(self, conn, sender, path, iface, prop):
        if iface == "org.mpris.MediaPlayer2":
            if prop == "Identity":
                return GLib.Variant('s', "JustCD")
            elif prop in ("CanQuit", "CanRaise"):
                return GLib.Variant('b', True)
            elif prop == "HasTrackList":
                return GLib.Variant('b', False)
            elif prop in ("SupportedUriSchemes", "SupportedMimeTypes"):
                return GLib.Variant('as', ["cdda"])
        elif iface == "org.mpris.MediaPlayer2.Player":
            if prop == "PlaybackStatus":
                return GLib.Variant('s', self.window.mpris_status)
            elif prop in ("CanControl", "CanPlay", "CanPause", "CanGoNext", "CanGoPrevious"):
                return GLib.Variant('b', True)
            elif prop == "Metadata":
                metadata = {
                    'mpris:trackid': GLib.Variant('o', f"/org/mpris/MediaPlayer2/Track/{self.window.current_track}"),
                    'xesam:title': GLib.Variant('s', self.window.title_label.get_label()),
                    'xesam:artist': GLib.Variant('as', [self.window.current_artist]),
                    'xesam:album': GLib.Variant('s', self.window.current_album),
                }
                return GLib.Variant('a{sv}', metadata)
        return None

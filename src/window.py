# === SECCIÓN 1: IMPORTACIÓN DE LIBRERÍAS Y TRADUCCIÓN DIRECTA ===
import gi
import os
import threading
import urllib.request
import urllib.parse
import json
import fcntl
import random
import subprocess
import struct
import re
import gettext

# --- CARGA DEL IDIOMA FORZADO (PURA Y DIRECTA) ---
def setup_i18n():
    # Usar XDG_CONFIG_HOME garantiza encontrar el archivo dentro del sandbox de Flatpak
    config_dir = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_path = os.path.join(config_dir, "justcd", "preferences.json")

    lang = "system"
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
                lang = data.get("language", "system")
    except Exception as e:
        print(f"[I18N] Error leyendo config: {e}")

    localedir = "/app/share/locale"

    # Si el usuario eligió un idioma específico (ej. "es", "de", "ca", etc.)
    if lang != "system":
        try:
            # Carga el archivo .mo de ese idioma directamente a la memoria
            trans = gettext.translation("justcd", localedir=localedir, languages=[lang])
            print(f"[I18N] ¡Idioma forzado con éxito desde configuración!: {lang}")
            return trans.gettext
        except Exception as e:
            print(f"[I18N AVISO] No se encontró traducción para '{lang}' ({e}). Usando base.")

    # Si es 'system' o no se pudo cargar, usar gettext normal
    try:
        gettext.bindtextdomain("justcd", localedir)
        gettext.textdomain("justcd")
        return gettext.gettext
    except Exception:
        return lambda s: s

# La función mágica de traducción '_' ahora responde al idioma elegido
_ = setup_i18n()

# Versiones de las librerías de GNOME
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gst', '1.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gio', '2.0')

from gi.repository import Adw, Gst, Gtk, GLib, Gdk, GdkPixbuf, Gio

# === SECCIÓN 2: INTEGRACIÓN CON EL SISTEMA (MPRIS) ===
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
        for iface in self.node_info.interfaces:
            connection.register_object("/org/mpris/MediaPlayer2", iface, self._handle_method_call, self._handle_get_property, None)

    def _handle_method_call(self, conn, sender, path, iface, method, params, invocation):
        if method in ("PlayPause", "Play", "Pause"): GLib.idle_add(self.window._on_play_pause_clicked, None)
        elif method == "Stop": GLib.idle_add(self.window._on_stop_clicked, None)
        elif method == "Next": GLib.idle_add(self.window._on_next_clicked, None)
        elif method == "Previous": GLib.idle_add(self.window._on_prev_clicked, None)
        elif method == "Raise": GLib.idle_add(self.window.present)
        invocation.return_value(None)

    def _handle_get_property(self, conn, sender, path, iface, prop):
        if iface == "org.mpris.MediaPlayer2":
            if prop == "Identity": return GLib.Variant('s', "JustCD")
            elif prop in ("CanQuit", "CanRaise"): return GLib.Variant('b', True)
            elif prop == "HasTrackList": return GLib.Variant('b', False)
            elif prop in ("SupportedUriSchemes", "SupportedMimeTypes"): return GLib.Variant('as', ["cdda"])
        elif iface == "org.mpris.MediaPlayer2.Player":
            if prop == "PlaybackStatus": return GLib.Variant('s', self.window.mpris_status)
            elif prop in ("CanControl", "CanPlay", "CanPause", "CanGoNext", "CanGoPrevious"): return GLib.Variant('b', True)
            elif prop == "Metadata":
                metadata = {
                    'mpris:trackid': GLib.Variant('o', f"/org/mpris/MediaPlayer2/Track/{self.window.current_track}"),
                    'xesam:title': GLib.Variant('s', self.window.title_label.get_label()),
                    'xesam:artist': GLib.Variant('as', [self.window.current_artist]),
                    'xesam:album': GLib.Variant('s', self.window.current_album),
                }
                return GLib.Variant('a{sv}', metadata)
        return None


# === SECCIÓN 3: VENTANA DE PREFERENCIAS ===
class PreferencesDialog(Adw.PreferencesWindow):
    def __init__(self, parent, **kwargs):
        super().__init__(**kwargs)
        self.set_title(_("Preferences"))
        self.set_transient_for(parent)
        self.parent = parent

        page = Adw.PreferencesPage()
        page.set_title(_("General"))
        page.set_icon_name("preferences-system-symbolic")

        # --- GRUPO 1: IDIOMA ---
        group_lang = Adw.PreferencesGroup()
        group_lang.set_title(_("Language"))

        self.LANG_CODES = ["system", "en", "es", "ca", "eu", "gl", "pt_PT", "pt_BR", "fr", "de", "it", "ru", "ja", "zh_CN"]
        lang_names = [
            _("System Default"), "English", "Español", "Català", "Euskara", "Galego",
            "Português (PT)", "Português (BR)", "Français", "Deutsch", "Italiano", "Русский", "日本語", "简体中文"
        ]

        model = Gtk.StringList.new(lang_names)
        self.row_lang = Adw.ComboRow()
        self.row_lang.set_title(_("Application Language"))
        self.row_lang.set_model(model)

        try:
            idx = self.LANG_CODES.index(parent.pref_language)
        except ValueError:
            idx = 0
        self.row_lang.set_selected(idx)
        self.row_lang.connect("notify::selected", self._on_lang_selected)
        group_lang.add(self.row_lang)

        # --- GRUPO 2: REPRODUCCIÓN ---
        group_playback = Adw.PreferencesGroup()
        group_playback.set_title(_("Playback"))

        self.row_autoplay = Adw.SwitchRow()
        self.row_autoplay.set_title(_("Automatic Playback"))
        self.row_autoplay.set_subtitle(_("Start music immediately when a CD is inserted"))
        self.row_autoplay.set_active(parent.pref_autoplay)
        self.row_autoplay.connect("notify::active", self._on_autoplay_toggled)
        group_playback.add(self.row_autoplay)

        self.row_autoeject = Adw.SwitchRow()
        self.row_autoeject.set_title(_("Eject on Finish"))
        self.row_autoeject.set_subtitle(_("Open the tray automatically when the album ends"))
        self.row_autoeject.set_active(parent.pref_autoeject)
        self.row_autoeject.connect("notify::active", self._on_autoeject_toggled)
        group_playback.add(self.row_autoeject)

        # --- GRUPO 3: RED Y PRIVACIDAD ---
        group_network = Adw.PreferencesGroup()
        group_network.set_title(_("Network and Privacy"))

        self.row_online = Adw.SwitchRow()
        self.row_online.set_title(_("Download Online Information"))
        self.row_online.set_subtitle(_("Query MusicBrainz for album covers and track names"))
        self.row_online.set_active(parent.pref_fetch_online)
        self.row_online.connect("notify::active", self._on_online_toggled)
        group_network.add(self.row_online)

        page.add(group_lang)
        page.add(group_playback)
        page.add(group_network)
        self.add(page)

    def _on_lang_selected(self, row, param):
        idx = row.get_selected()
        self.parent.pref_language = self.LANG_CODES[idx]
        self.parent._save_preferences()
        # Avisar al usuario que necesita reiniciar la app para aplicar el idioma
        self.row_lang.set_subtitle(_("Restart required to apply changes"))

    def _on_autoplay_toggled(self, row, param):
        self.parent.pref_autoplay = row.get_active()
        self.parent._save_preferences()

    def _on_autoeject_toggled(self, row, param):
        self.parent.pref_autoeject = row.get_active()
        self.parent._save_preferences()

    def _on_online_toggled(self, row, param):
        self.parent.pref_fetch_online = row.get_active()
        self.parent._save_preferences()


# === SECCIÓN 4: VENTANA PRINCIPAL DE JUSTCD ===
class JustCDWindow(Adw.ApplicationWindow):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("JustCD")
        self.set_default_size(860, 640)

        # Estado del reproductor
        self.player = None
        self.current_track = 1
        self.total_tracks = 1
        self.duration_seconds = 0
        self.is_seeking = False
        self.timer_id = None
        self.mpris_status = "Stopped"
        self.current_artist = _("Audio CD")
        self.current_album = _("Unknown")
        self.mbid_fetched = False
        self.current_indicator = None

        self.ignore_row_activated = False
        self.is_shuffle = False
        self.repeat_mode = 0
        self.unplayed_tracks = []
        self.saved_volume_before_mute = 1.0

        self.current_cover_pixbuf = None
        self.connect("notify::maximized", self._on_maximized_changed)

        # Preferencias
        self.pref_autoplay = False
        self.pref_autoeject = False
        self.pref_fetch_online = True
        self.pref_volume = 1.0
        self.pref_language = "system"
        self._load_preferences()

        self.drive_state = "UNKNOWN"

        self._setup_player()
        self._build_ui()
        self._setup_shortcuts()
        self.mpris = MPRISService(self)

        self._update_cover_size()
        self._setup_hardware_monitor()
        GLib.timeout_add(1500, self._hardware_watchdog)
        GLib.timeout_add(1500, self._check_disc_on_startup)

    def _get_config_path(self):
        config_dir = os.path.join(GLib.get_user_config_dir(), "justcd")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "preferences.json")

    def _load_preferences(self):
        try:
            path = self._get_config_path()
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                    self.pref_autoplay = data.get("autoplay", False)
                    self.pref_autoeject = data.get("autoeject", False)
                    self.pref_fetch_online = data.get("fetch_online", True)
                    self.pref_volume = data.get("volume", 1.0)
                    self.pref_language = data.get("language", "system")
        except Exception:
            pass

    def _save_preferences(self):
        try:
            path = self._get_config_path()
            data = {
                "autoplay": self.pref_autoplay,
                "autoeject": self.pref_autoeject,
                "fetch_online": self.pref_fetch_online,
                "volume": getattr(self, "pref_volume", 1.0),
                "language": getattr(self, "pref_language", "system")
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _setup_player(self):
        self.player = Gst.ElementFactory.make("playbin", "player")
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        self.player.connect("source-setup", self._on_source_setup)

    def _setup_shortcuts(self):
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if keyval == Gdk.KEY_space:
            if self.btn_play_pause.get_sensitive():
                self._on_play_pause_clicked(self.btn_play_pause)
                return True
        elif keyval == Gdk.KEY_Right and is_ctrl:
            if self.btn_next.get_sensitive():
                self._on_next_clicked(self.btn_next)
                return True
        elif keyval == Gdk.KEY_Left and is_ctrl:
            if self.btn_prev.get_sensitive():
                self._on_prev_clicked(self.btn_prev)
                return True
        elif keyval == Gdk.KEY_Right:
            if self.player and self.player.get_state(0)[1] == Gst.State.PLAYING:
                self._seek_relative(5)
                return True
        elif keyval == Gdk.KEY_Left:
            if self.player and self.player.get_state(0)[1] == Gst.State.PLAYING:
                self._seek_relative(-5)
                return True
        elif (keyval in (Gdk.KEY_e, Gdk.KEY_E)) and is_ctrl:
            self._on_eject_clicked(self.btn_eject)
            return True
        elif (keyval in (Gdk.KEY_m, Gdk.KEY_M)) and is_ctrl:
            if self.btn_vol_mute.get_sensitive():
                self._on_mute_clicked(self.btn_vol_mute)
                return True
        elif (keyval == Gdk.KEY_comma) and is_ctrl:
            self._show_preferences_dialog()
            return True
        return False

    def _seek_relative(self, delta_seconds):
        success, position = self.player.query_position(Gst.Format.TIME)
        if success:
            current_sec = position / Gst.SECOND
            target_sec = max(0, min(self.duration_seconds, current_sec + delta_seconds))
            seek_pos_ns = int(target_sec * Gst.SECOND)
            self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, seek_pos_ns)
            self.time_slider.set_value(target_sec)
            self.time_current_label.set_label(self._format_time(target_sec))

    def _build_ui(self):
        paned = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        paned.set_margin_top(20)
        paned.set_margin_bottom(20)
        paned.set_margin_start(24)
        paned.set_margin_end(24)

        # Panel Izquierdo
        self.left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        cover_container = Gtk.Box(halign=Gtk.Align.CENTER)
        self.cover_image = Gtk.Image.new_from_icon_name("media-optical-cd-audio-symbolic")
        self.cover_image.set_pixel_size(250)
        self.cover_image.add_css_class("card")
        cover_container.append(self.cover_image)
        self.left_box.append(cover_container)

        self.title_label = Gtk.Label(label=_("Insert an Audio CD"))
        self.title_label.add_css_class("title-2")
        self.title_label.set_ellipsize(3)

        self.artist_label = Gtk.Label(label=_("Audio CD"))
        self.artist_label.add_css_class("dim-label")
        self.artist_label.add_css_class("subtitle")
        self.artist_label.set_ellipsize(3)

        self.left_box.append(self.title_label)
        self.left_box.append(self.artist_label)

        # Barra de progreso
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.time_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.time_slider.set_draw_value(False)
        self.time_slider.set_hexpand(True)
        self.time_slider.connect("change-value", self._on_slider_change_value)

        time_labels_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.time_current_label = Gtk.Label(label="00:00")
        self.time_current_label.add_css_class("dim-label")
        self.time_total_label = Gtk.Label(label="00:00")
        self.time_total_label.add_css_class("dim-label")
        self.time_total_label.set_hexpand(True)
        self.time_total_label.set_halign(Gtk.Align.END)
        time_labels_box.append(self.time_current_label)
        time_labels_box.append(self.time_total_label)
        progress_box.append(self.time_slider)
        progress_box.append(time_labels_box)
        self.left_box.append(progress_box)

        # Controles Multimedia
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14, halign=Gtk.Align.CENTER)

        self.btn_shuffle = Gtk.ToggleButton()
        self.btn_shuffle.set_icon_name("media-playlist-shuffle-symbolic")
        self.btn_shuffle.add_css_class("circular")
        self.btn_shuffle.set_tooltip_text(_("Random playback"))
        self.btn_shuffle.connect("toggled", self._on_shuffle_toggled)

        self.btn_prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.btn_prev.add_css_class("circular")
        self.btn_prev.connect("clicked", self._on_prev_clicked)

        self.btn_play_pause = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.btn_play_pause.add_css_class("pill")
        self.btn_play_pause.set_size_request(58, 44)
        self.btn_play_pause.connect("clicked", self._on_play_pause_clicked)

        self.btn_stop = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic")
        self.btn_stop.add_css_class("circular")
        self.btn_stop.connect("clicked", self._on_stop_clicked)

        self.btn_next = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.btn_next.add_css_class("circular")
        self.btn_next.connect("clicked", self._on_next_clicked)

        self.btn_repeat = Gtk.Button.new_from_icon_name("media-playlist-repeat-symbolic")
        self.btn_repeat.add_css_class("circular")
        self.btn_repeat.set_tooltip_text(_("Repeat: Disabled"))
        self.btn_repeat.connect("clicked", self._on_repeat_clicked)

        controls_box.append(self.btn_shuffle)
        controls_box.append(self.btn_prev)
        controls_box.append(self.btn_play_pause)
        controls_box.append(self.btn_stop)
        controls_box.append(self.btn_next)
        controls_box.append(self.btn_repeat)
        self.left_box.append(controls_box)

        # Volumen
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        self.btn_vol_mute = Gtk.Button.new_from_icon_name("audio-volume-medium-symbolic")
        self.btn_vol_mute.add_css_class("flat")
        self.btn_vol_mute.add_css_class("circular")
        self.btn_vol_mute.set_tooltip_text(_("Mute / Restore volume"))
        self.btn_vol_mute.connect("clicked", self._on_mute_clicked)

        self.vol_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1.0, 0.05)
        self.vol_slider.set_value(self.pref_volume)
        self.vol_slider.set_size_request(150, -1)
        self.vol_slider.set_draw_value(False)
        self.vol_slider.connect("value-changed", self._on_volume_changed)
        vol_box.append(self.btn_vol_mute)
        vol_box.append(self.vol_slider)
        self.left_box.append(vol_box)

        # Panel Derecho (Tracklist)
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right_box.set_hexpand(True)
        right_box.set_size_request(240, -1)

        list_title = Gtk.Label(label=_("Track List"), halign=Gtk.Align.START)
        list_title.add_css_class("heading")
        right_box.append(list_title)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        self.track_listbox = Gtk.ListBox()
        self.track_listbox.add_css_class("boxed-list")
        self.track_listbox.connect("row-activated", self._on_track_row_activated)
        scrolled.set_child(self.track_listbox)
        right_box.append(scrolled)

        paned.append(self.left_box)
        paned.append(right_box)

        # Barra Superior
        toolbar = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()

        app_icon_symbolic = Gtk.Image.new_from_icon_name("io.github.marcopcabrera.JustCD-symbolic")
        header_bar.pack_start(app_icon_symbolic)

        self.btn_eject = Gtk.Button.new_from_icon_name("media-eject-symbolic")
        self.btn_eject.set_tooltip_text(_("Eject disc"))
        self.btn_eject.connect("clicked", self._on_eject_clicked)
        header_bar.pack_end(self.btn_eject)

        menu = Gio.Menu.new()
        menu.append(_("Preferences"), "win.preferences")
        menu.append(_("Keyboard Shortcuts"), "win.show-help-overlay")
        menu.append(_("About JustCD"), "win.about")

        action_prefs = Gio.SimpleAction.new("preferences", None)
        action_prefs.connect("activate", self._show_preferences_dialog)
        self.add_action(action_prefs)

        action_shortcuts = Gio.SimpleAction.new("show-help-overlay", None)
        action_shortcuts.connect("activate", lambda a, p: self._show_shortcuts_window())
        self.add_action(action_shortcuts)

        action_about = Gio.SimpleAction.new("about", None)
        action_about.connect("activate", self._show_about_dialog)
        self.add_action(action_about)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        menu_btn.set_tooltip_text(_("Options"))
        header_bar.pack_end(menu_btn)

        toolbar.add_top_bar(header_bar)
        toolbar.set_content(paned)
        self.set_content(toolbar)

        self._set_controls_sensitive(False)

    def _show_about_dialog(self, action, param):
        about = Adw.AboutDialog()

        if hasattr(about, "set_content_height"):
            about.set_content_height(680)
            about.set_content_width(440)
        elif hasattr(about, "set_default_size"):
            about.set_default_size(440, 680)

        about.set_application_name("JustCD")
        about.set_version("1.0.0")
        about.set_developer_name("Marco P. Cabrera")
        about.set_application_icon("io.github.marcopcabrera.JustCD")

        about.set_website("https://github.com/marcopcabrera/JustCD")
        about.set_copyright("© 2026 Marco P. Cabrera")
        about.set_license_type(Gtk.License.GPL_3_0)

        about.set_developers([
            "Marco P. Cabrera (Project Direction & Integration)"
        ])
        about.set_designers([
            "Marco P. Cabrera (UX/UI Design)"
        ])
        about.set_artists([
            "Marco P. Cabrera"
        ])
        about.set_translator_credits(_("translator-credits"))

        about.add_acknowledgement_section(_("Open Source Technologies"), [
            "MusicBrainz",
            "Cover Art Archive",
            "GStreamer",
            "Libcdio"
        ])
        about.add_acknowledgement_section(_("Technical Assistance"), [
            "Gemini (AI Code Engine)"
        ])

        about.present(self)

    def _show_preferences_dialog(self, action=None, param=None):
        dialog = PreferencesDialog(self)
        dialog.present()

    def _show_shortcuts_window(self):
        builder = Gtk.Builder.new_from_resource("/io/github/marcopcabrera/JustCD/gtk/help-overlay.ui")
        shortcuts_win = builder.get_object("help_overlay")
        shortcuts_win.set_transient_for(self)
        shortcuts_win.present()

    def _set_controls_sensitive(self, sensitive=True):
        self.btn_play_pause.set_sensitive(sensitive)
        self.btn_stop.set_sensitive(sensitive)
        self.btn_prev.set_sensitive(sensitive)
        self.btn_next.set_sensitive(sensitive)
        self.btn_shuffle.set_sensitive(sensitive)
        self.btn_repeat.set_sensitive(sensitive)
        self.time_slider.set_sensitive(sensitive)
        self.vol_slider.set_sensitive(sensitive)
        self.btn_vol_mute.set_sensitive(sensitive)

    def _on_maximized_changed(self, window, param):
        self._update_cover_size()

    def _update_cover_size(self):
        is_max = self.is_maximized()
        size = 400 if is_max else 250

        if hasattr(self, "left_box"):
            self.left_box.set_size_request(540 if is_max else 380, -1)

        self.cover_image.set_pixel_size(size)

        if self.current_cover_pixbuf:
            scaled = self.current_cover_pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            texture = Gdk.Texture.new_for_pixbuf(scaled)
            self.cover_image.set_from_paintable(texture)

    # --- Hardware y Estado ---

    def _hardware_watchdog(self):
        if self.drive_state == "READING": return True
        if self.player and self.player.get_state(0)[1] == Gst.State.PLAYING: return True

        device = "/dev/sr0" if os.path.exists("/dev/sr0") else "/dev/cdrom"
        fd = None
        try:
            fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
            status = fcntl.ioctl(fd, 0x5326, 0)
            os.close(fd)
            fd = None

            if status == 4:
                if self.drive_state != "DISC_READY":
                    self.drive_state = "READING"
                    self._start_disc_read()
            else:
                if self.drive_state == "DISC_READY" or self.drive_state == "UNKNOWN":
                    self.drive_state = "TRAY_OPEN"
                    self._on_disc_removed()
        except Exception:
            pass
        finally:
            if fd is not None: os.close(fd)
        return True

    def _start_disc_read(self, retries=5):
        device = "/dev/sr0" if os.path.exists("/dev/sr0") else "/dev/cdrom"
        fd = None
        try:
            fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
            header = fcntl.ioctl(fd, 0x5305, struct.pack("BB", 0, 0))
            first_track, last_track = struct.unpack("BB", header)
            total_tracks = last_track - first_track + 1

            if total_tracks > 0:
                self.drive_state = "DISC_READY"
                self.total_tracks = total_tracks
                self.btn_eject.set_tooltip_text(_("Eject disc"))

                GLib.idle_add(self._populate_tracklist_default, total_tracks)

                if self.pref_fetch_online and not self.mbid_fetched:
                    GLib.idle_add(self._fetch_tags_silent_probe)
                elif self.pref_autoplay:
                    GLib.idle_add(self._play_track, 1)

                return False
        except Exception:
            if retries > 0:
                GLib.timeout_add(1000, self._start_disc_read, retries - 1)
                return False
            else:
                self.drive_state = "TRAY_OPEN"
                self._clear_all_metadata(_("Insert an Audio CD"))
        finally:
            if fd is not None: os.close(fd)
        return False

    def _setup_hardware_monitor(self):
        try:
            self.vol_monitor = Gio.VolumeMonitor.get()
            self.vol_monitor.connect("mount-added", self._on_gvfs_mount_added)
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            bus.signal_subscribe("org.freedesktop.UDisks2", "org.freedesktop.DBus.Properties", "PropertiesChanged", None, None, Gio.DBusSignalFlags.NONE, self._on_udisks_property_changed, None)
        except Exception:
            pass

    def _on_gvfs_mount_added(self, monitor, mount):
        scheme = mount.get_default_location().get_uri_scheme()
        if scheme == "cdda" or "Audio" in mount.get_name():
            self.is_tray_open = False
            self.btn_eject.set_tooltip_text(_("Eject disc"))
            self.title_label.set_label(_("Reading CD…"))
            self.artist_label.set_label(_("Loading tracks…"))
            GLib.timeout_add(2500, self._start_disc_read, 5)

    def _on_udisks_property_changed(self, conn, sender, path, iface, signal, params):
        if "/sr0" in path or "/drives/" in path:
            props = params.get_child_value(1)
            disc_ejected = False
            if props.has_key("MediaAvailable"):
                if not props.lookup_value("MediaAvailable", GLib.VariantType("b")).get_boolean(): disc_ejected = True
            if props.has_key("Media"):
                if not props.lookup_value("Media", GLib.VariantType("s")).get_string(): disc_ejected = True

            if disc_ejected and not self.is_tray_open:
                GLib.idle_add(self._on_disc_removed)

    def _on_disc_removed(self):
        self._set_ui_stopped()
        self.is_tray_open = True
        self.btn_eject.set_tooltip_text(_("Close tray"))
        self._clear_all_metadata(_("Tray Open / No CD"))

    def _check_disc_on_startup(self):
        # Comprobar si hay disco físicamente antes de hacer nada al arrancar
        device = "/dev/sr0" if os.path.exists("/dev/sr0") else "/dev/cdrom"
        try:
            fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
            status = fcntl.ioctl(fd, 0x5326, 0) # CDROM_DRIVE_STATUS
            os.close(fd)
            if status == 4:  # CDS_DISC_OK (Hay disco)
                print("[STARTUP] CD detectado en la unidad.")
                self._start_disc_read()
            else:
                print("[STARTUP] Unidad vacía.")
                self.drive_state = "TRAY_OPEN"
                self._clear_all_metadata(_("Insert an Audio CD"))
        except Exception:
            pass
        return False


    def _populate_tracklist_default(self, total):
        self.current_indicator = None
        while row := self.track_listbox.get_row_at_index(0):
            self.track_listbox.remove(row)

        for i in range(1, total + 1):
            row = Adw.ActionRow()
            row.set_title(_("Track %d") % i)
            row.set_subtitle(_("Audio CD"))
            row.track_num = i
            row.set_activatable(True)
            row.set_title_lines(1)
            row.set_subtitle_lines(1)

            indicator = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
            indicator.add_css_class("accent")
            indicator.set_visible(False)
            row.add_suffix(indicator)
            row.indicator = indicator
            self.track_listbox.append(row)

        self.title_label.set_label(_("Track 1"))
        self.artist_label.set_label(_("Audio CD"))

        row1 = self.track_listbox.get_row_at_index(0)
        if row1:
            self.ignore_row_activated = True
            self.track_listbox.select_row(row1)
            self.ignore_row_activated = False

        self._set_controls_sensitive(True)
        return False

    def _clear_all_metadata(self, status_msg=None):
        if status_msg is None: status_msg = _("Insert an Audio CD")
        self.title_label.set_label(status_msg)
        self.artist_label.set_label(_("Audio CD"))
        self.cover_image.set_from_icon_name("media-optical-cd-audio-symbolic")
        self.mbid_fetched = False
        self.total_tracks = 1
        self.current_track = 1
        self.current_cover_pixbuf = None

        self.btn_play_pause.remove_css_class("suggested-action")
        self._set_controls_sensitive(False)
        self._update_cover_size()

        self.time_slider.set_value(0)
        self.time_current_label.set_label("00:00")
        self.time_total_label.set_label("00:00")

        if self.current_indicator:
            self.current_indicator.set_visible(False)
            self.current_indicator = None

        while row := self.track_listbox.get_row_at_index(0):
            self.track_listbox.remove(row)

    # --- Sonda Silenciosa e Internet ---

    def _fetch_tags_silent_probe(self):
        self.title_label.set_label(_("Identifying album…"))
        self.artist_label.set_label(_("Querying MusicBrainz…"))

        device = "/dev/sr0" if os.path.exists("/dev/sr0") else "/dev/cdrom"
        probe_pipe = Gst.parse_launch(f"cdiocddasrc device={device} ! fakesink")
        bus = probe_pipe.get_bus()
        bus.add_signal_watch()

        def _on_probe_msg(b, msg):
            if msg.type == Gst.MessageType.TAG:
                tag_list = msg.parse_tag()
                discid = None
                succ, val = tag_list.get_string("musicbrainz-discid")
                if succ and val: discid = val
                else:
                    succ, val = tag_list.get_string("discid")
                    if succ and val: discid = val

                if discid and not self.mbid_fetched:
                    self.mbid_fetched = True
                    probe_pipe.set_state(Gst.State.NULL)
                    threading.Thread(target=self._fetch_metadata_and_cover, args=(discid,), daemon=True).start()

            elif msg.type in (Gst.MessageType.ERROR, Gst.MessageType.EOS):
                probe_pipe.set_state(Gst.State.NULL)
                GLib.idle_add(self._restore_offline_ui)

        bus.connect("message", _on_probe_msg)
        probe_pipe.set_state(Gst.State.PLAYING)
        GLib.timeout_add(1500, lambda: probe_pipe.set_state(Gst.State.NULL) and False)
        return False

    def _restore_offline_ui(self):
        if self.title_label.get_label() == _("Identifying album…"):
            row = self.track_listbox.get_row_at_index(self.current_track - 1)
            self.title_label.set_label(row.get_title() if row else _("Track %d") % self.current_track)
            self.artist_label.set_label(_("Audio CD"))
            if self.pref_autoplay:
                self._play_track(1)
        return False

    def _download_image(self, url):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (JustCD/1.0)'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf: return pixbuf.scale_simple(400, 400, GdkPixbuf.InterpType.BILINEAR)
        return None

    def _fetch_metadata_and_cover(self, discid):
        album, artist = _("Unknown Album"), _("Unknown Artist")
        release_id, release_group_id, tracks = None, None, []

        try:
            mb_url = f"https://musicbrainz.org/ws/2/discid/{discid}?fmt=json&inc=recordings+artists+release-groups"
            req = urllib.request.Request(mb_url, headers={'User-Agent': 'JustCD/1.0 ( marco@example.com )'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                releases = data.get("releases", [])
                if releases:
                    rel = releases[0]
                    release_id = rel.get("id")
                    release_group_id = rel.get("release-group", {}).get("id")
                    album = rel.get("title", album)
                    artist = rel.get("artist-credit", [{}])[0].get("name", artist)
                    tracks = rel.get("media", [{}])[0].get("tracks", [])
                    GLib.idle_add(self._apply_musicbrainz_metadata, album, artist, tracks)
        except Exception:
            GLib.idle_add(self._restore_offline_ui)

        pixbuf = None
        if release_id:
            try: pixbuf = self._download_image(f"https://coverartarchive.org/release/{release_id}/front-500")
            except Exception: pass
        if not pixbuf and release_group_id:
            try: pixbuf = self._download_image(f"https://coverartarchive.org/release-group/{release_group_id}/front-500")
            except Exception: pass

        if not pixbuf and album != _("Unknown Album"):
            try:
                query = urllib.parse.quote(f"{artist} {album}")
                itunes_url = f"https://itunes.apple.com/search?term={query}&entity=album&limit=1"
                req = urllib.request.Request(itunes_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    itunes_data = json.loads(resp.read().decode())
                    results = itunes_data.get("results", [])
                    if results:
                        art_url = results[0].get("artworkUrl100", "").replace("100x100bb", "600x600bb")
                        if art_url: pixbuf = self._download_image(art_url)
            except Exception: pass

        if pixbuf:
            GLib.idle_add(self._apply_cover_art, pixbuf)

    def _apply_cover_art(self, pixbuf):
        self.current_cover_pixbuf = pixbuf
        self._update_cover_size()
        return False

    def _apply_musicbrainz_metadata(self, album, artist, tracks):
        self.current_album = album
        self.current_artist = artist
        self.artist_label.set_label(f"{artist} — {album}")
        self.current_indicator = None
        self.total_tracks = len(tracks)

        while row := self.track_listbox.get_row_at_index(0):
            self.track_listbox.remove(row)

        for tr in tracks:
            num = int(tr.get("position", 1))
            title = tr.get("title", _("Track %d") % num).replace("&", "&amp;")

            length_ms = tr.get("length")
            duration_str = self._format_time(length_ms / 1000) if length_ms else ""

            row = Adw.ActionRow()
            row.set_title(f"{num}. {title}")
            row.set_subtitle(artist)
            row.track_num = num
            row.set_activatable(True)
            row.set_title_lines(1)
            row.set_subtitle_lines(1)

            if duration_str:
                dur_label = Gtk.Label(label=duration_str)
                dur_label.add_css_class("dim-label")
                dur_label.add_css_class("numeric")
                row.add_suffix(dur_label)

            indicator = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
            indicator.add_css_class("accent")
            indicator.set_visible(False)
            row.add_suffix(indicator)
            row.indicator = indicator
            self.track_listbox.append(row)

        if self.current_track <= len(tracks):
            self.title_label.set_label(tracks[self.current_track - 1].get("title", _("Track %d") % self.current_track).replace("&", "&amp;"))
            active_row = self.track_listbox.get_row_at_index(self.current_track - 1)
            if active_row:
                self.ignore_row_activated = True
                self.track_listbox.select_row(active_row)
                active_row.grab_focus()
                self.ignore_row_activated = False

        self._set_controls_sensitive(True)
        if self.pref_autoplay and self.mpris_status == "Stopped":
            self._play_track(1)
        return False

    # --- GStreamer ---

    def _on_source_setup(self, playbin, source):
        device_path = "/dev/sr0" if os.path.exists("/dev/sr0") else "/dev/cdrom"
        if source.find_property("device"):
            source.set_property("device", device_path)

    def _on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            self._set_ui_stopped()
        elif t == Gst.MessageType.EOS:
            self.player.set_state(Gst.State.NULL)
            GLib.idle_add(self._handle_track_finished)
        elif t == Gst.MessageType.TAG:
            tag_list = message.parse_tag()
            discid = None
            succ, val = tag_list.get_string("musicbrainz-discid")
            if succ and val: discid = val
            else:
                succ, val = tag_list.get_string("discid")
                if succ and val: discid = val

            if discid and not self.mbid_fetched:
                self.mbid_fetched = True
                threading.Thread(target=self._fetch_metadata_and_cover, args=(discid,), daemon=True).start()

    def _handle_track_finished(self):
        self._on_next_clicked(None)
        return False

    def _play_track(self, track_number):
        self.current_track = track_number

        if self.current_indicator:
            self.current_indicator.set_visible(False)
            self.current_indicator = None

        row = self.track_listbox.get_row_at_index(track_number - 1)
        if row:
            self.title_label.set_label(row.get_title())
            self.ignore_row_activated = True
            self.track_listbox.select_row(row)
            row.grab_focus()
            self.ignore_row_activated = False

            if hasattr(row, "indicator"):
                row.indicator.set_visible(True)
                self.current_indicator = row.indicator
        else:
            self.title_label.set_label(_("Track %d") % track_number)

        self.player.set_state(Gst.State.NULL)
        uri = f"cdda://{track_number}"
        self.player.set_property("uri", uri)
        self.player.set_property("mute", False)
        self.player.set_property("volume", self.vol_slider.get_value())

        ret = self.player.set_state(Gst.State.PLAYING)
        if ret != Gst.StateChangeReturn.FAILURE:
            self.mpris_status = "Playing"
            self.btn_play_pause.set_icon_name("media-playback-pause-symbolic")
            self.btn_play_pause.add_css_class("suggested-action")
            if not self.timer_id:
                self.timer_id = GLib.timeout_add(250, self._update_ui_timer)

    def _on_play_pause_clicked(self, button):
        success, state, pending = self.player.get_state(0)
        if state == Gst.State.PLAYING:
            self.player.set_state(Gst.State.PAUSED)
            self.mpris_status = "Paused"
            self.btn_play_pause.set_icon_name("media-playback-start-symbolic")
            self.btn_play_pause.remove_css_class("suggested-action")
            if self.timer_id:
                GLib.source_remove(self.timer_id)
                self.timer_id = None
        elif state == Gst.State.PAUSED:
            self.player.set_state(Gst.State.PLAYING)
            self.mpris_status = "Playing"
            self.btn_play_pause.set_icon_name("media-playback-pause-symbolic")
            self.btn_play_pause.add_css_class("suggested-action")
            if not self.timer_id:
                self.timer_id = GLib.timeout_add(250, self._update_ui_timer)
        else:
            self._play_track(self.current_track)

    def _on_stop_clicked(self, button):
        self._set_ui_stopped()

    def _set_ui_stopped(self):
        if self.player:
            self.player.set_state(Gst.State.NULL)
        self.mpris_status = "Stopped"
        self.btn_play_pause.set_icon_name("media-playback-start-symbolic")
        self.btn_play_pause.remove_css_class("suggested-action")
        self.time_slider.set_value(0)
        self.time_current_label.set_label("00:00")

        if self.current_indicator:
            self.current_indicator.set_visible(False)
            self.current_indicator = None

        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

    def _on_prev_clicked(self, button):
        success, position = self.player.query_position(Gst.Format.TIME)
        pos_seconds = (position / Gst.SECOND) if success else 0

        if pos_seconds > 3.0:
            self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
            self.time_slider.set_value(0)
            self.time_current_label.set_label("00:00")
            return

        if self.current_track > 1:
            self._play_track(self.current_track - 1)

    def _on_next_clicked(self, button):
        if self.repeat_mode == 2 and button is None:
            self._play_track(self.current_track)
            return

        row_count = 0
        while self.track_listbox.get_row_at_index(row_count) is not None:
            row_count += 1
        total = max(self.total_tracks, row_count, 1)

        if self.is_shuffle:
            if not self.unplayed_tracks:
                if self.repeat_mode >= 1:
                    self._reset_unplayed_tracks()
                else:
                    self._set_ui_stopped()
                    if self.pref_autoeject: self._on_eject_clicked(self.btn_eject)
                    return

            if self.unplayed_tracks:
                next_track = random.choice(self.unplayed_tracks)
                self.unplayed_tracks.remove(next_track)
                self._play_track(next_track)
            return

        if self.current_track < total:
            self._play_track(self.current_track + 1)
        else:
            if self.repeat_mode >= 1:
                self._play_track(1)
            else:
                self._set_ui_stopped()
                if self.pref_autoeject and button is None:
                    self._on_eject_clicked(self.btn_eject)

    def _on_track_row_activated(self, listbox, row):
        if self.ignore_row_activated: return
        if hasattr(row, "track_num"): self._play_track(row.track_num)

    def _on_slider_change_value(self, slider, scroll, value):
        self.is_seeking = True
        seek_pos_ns = int(value * Gst.SECOND)
        self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, seek_pos_ns)
        self.time_current_label.set_label(self._format_time(value))
        self.is_seeking = False
        return False

    def _on_mute_clicked(self, button):
        current_vol = self.vol_slider.get_value()
        if current_vol > 0:
            self.saved_volume_before_mute = current_vol
            self.vol_slider.set_value(0.0)
        else:
            self.vol_slider.set_value(getattr(self, "saved_volume_before_mute", 0.8))

    def _on_volume_changed(self, slider):
        val = slider.get_value()
        if self.player:
            self.player.set_property("volume", val)

        if val == 0: self.btn_vol_mute.set_icon_name("audio-volume-muted-symbolic")
        elif val < 0.5: self.btn_vol_mute.set_icon_name("audio-volume-low-symbolic")
        else: self.btn_vol_mute.set_icon_name("audio-volume-medium-symbolic")

        if val > 0:
            self.pref_volume = val
            self._save_preferences()

    def _format_time(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def _update_ui_timer(self):
        if not self.player or self.is_seeking: return True
        success, duration = self.player.query_duration(Gst.Format.TIME)
        if success and duration > 0:
            self.duration_seconds = duration / Gst.SECOND
            self.time_slider.set_range(0, self.duration_seconds)
            self.time_total_label.set_label(self._format_time(self.duration_seconds))
        success, position = self.player.query_position(Gst.Format.TIME)
        if success and position >= 0:
            pos_seconds = position / Gst.SECOND
            self.time_slider.set_value(pos_seconds)
            self.time_current_label.set_label(self._format_time(pos_seconds))
        return True

    # --- Expulsión de Bandeja ---

    def _on_eject_clicked(self, button):
        self._set_ui_stopped()
        device = "/dev/sr0" if os.path.exists("/dev/sr0") else "/dev/cdrom"

        if self.drive_state == "TRAY_OPEN":
            try:
                fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
                fcntl.ioctl(fd, 0x5319, 0) # CDROMCLOSETRAY
                os.close(fd)
            except Exception:
                subprocess.run(["flatpak-spawn", "--host", "eject", "-t", device], capture_output=True)
            self.drive_state = "READING"
            self.btn_eject.set_tooltip_text(_("Eject disc"))
            self.title_label.set_label(_("Reading CD…"))
            self.artist_label.set_label(_("Loading tracks…"))
            GLib.timeout_add(1500, self._start_disc_read, 5)
            return

        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            block_proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None, "org.freedesktop.UDisks2", "/org/freedesktop/UDisks2/block_devices/sr0", "org.freedesktop.UDisks2.Block", None)
            drive_path = block_proxy.get_cached_property("Drive").get_string()
            drive_proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None, "org.freedesktop.UDisks2", drive_path, "org.freedesktop.UDisks2.Drive", None)
            drive_proxy.call_sync("Eject", GLib.Variant("(a{sv})", ({},)), Gio.DBusCallFlags.NONE, -1, None)
        except Exception:
            subprocess.run(["flatpak-spawn", "--host", "eject", device], capture_output=True)

        self.drive_state = "TRAY_OPEN"
        self._on_disc_removed()

    def _on_shuffle_toggled(self, button):
        self.is_shuffle = button.get_active()
        if self.is_shuffle:
            button.add_css_class("suggested-action")
            if self.repeat_mode == 2:
                self.repeat_mode = 1
                self.btn_repeat.set_icon_name("media-playlist-repeat-symbolic")
                self.btn_repeat.set_tooltip_text(_("Repeat: Full disc"))
        else:
            button.remove_css_class("suggested-action")
        self._reset_unplayed_tracks()

    def _on_repeat_clicked(self, button):
        self.repeat_mode = (self.repeat_mode + 1) % 3
        if self.repeat_mode == 0:
            button.remove_css_class("suggested-action")
            button.set_icon_name("media-playlist-repeat-symbolic")
            button.set_tooltip_text(_("Repeat: Disabled"))
        elif self.repeat_mode == 1:
            button.add_css_class("suggested-action")
            button.set_icon_name("media-playlist-repeat-symbolic")
            button.set_tooltip_text(_("Repeat: Full disc"))
        elif self.repeat_mode == 2:
            button.add_css_class("suggested-action")
            button.set_icon_name("media-playlist-repeat-song-symbolic")
            button.set_tooltip_text(_("Repeat: Current track"))
            if self.is_shuffle:
                self.is_shuffle = False
                self.btn_shuffle.set_active(False)
                self.btn_shuffle.remove_css_class("suggested-action")

    def _reset_unplayed_tracks(self):
        row_count = 0
        while self.track_listbox.get_row_at_index(row_count) is not None: row_count += 1
        self.unplayed_tracks = [i for i in range(1, max(self.total_tracks, row_count, 1) + 1) if i != self.current_track]

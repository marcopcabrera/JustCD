import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gst', '1.0')

from gi.repository import Adw, Gst
from justcd.window import JustCDWindow


class JustCDApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.marcopcabrera.JustCD")
        Gst.init(None)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = JustCDWindow(application=self)
        win.present()


def main(version=None):
    app = JustCDApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

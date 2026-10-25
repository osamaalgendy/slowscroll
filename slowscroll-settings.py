#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Osama Algendy <71908505+osamaalgendy@users.noreply.github.com>
"""Settings window for slowscroll (GTK4 + libadwaita).

Edits ~/.config/slowscroll.conf; the slowscroll service re-reads it within a
second, so every change is applied live.
"""
import os
import subprocess
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402


def _lang_is_arabic():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v:
            return v.split(":")[0].lower().startswith("ar")
    return False


IS_ARABIC = _lang_is_arabic()
AR = {
    'Reset to default': 'إرجاع للقيمة الافتراضية',
    'Touchpad scrolling': 'سرعة التمرير في الـ Touchpad',
    'Restore defaults': 'استعادة الافتراضي',
    'Enable Slowscroll': 'تشغيل Slowscroll',
    'When off, the touchpad uses the system settings': 'لما يكون مقفول بيرجع الـ touchpad لإعدادات النظام',
    'Two-finger scrolling': 'التمرير بإصبعين',
    'Speed applies to both fingers moving together; pinch-zoom is not affected': 'السرعة بتتطبق على حركة الإصبعين مع بعض، والـ pinch zoom مش بيتأثر',
    'Speed': 'السرعة',
    'Default = Mac speed: content follows your fingers exactly': 'الافتراضي = سرعة الماك: المحتوى بيتحرك مع صوابعك بالظبط',
    'Mac': 'ماك',
    'System': 'النظام',
    'Constant': 'ثابت',
    'Acceleration': 'التسارع',
    'Slow movement = precise, fast flick = farther': 'حركة بطيئة = دقيقة، flick سريع = مسافة أكبر',
    'Momentum after lifting fingers': 'الانزلاق بعد رفع الأصابع',
    'Same feel in every app; touching the touchpad stops it': 'نفس الإحساس في كل البرامج، ولمس الـ touchpad بيوقفه',
    'Enable momentum': 'تفعيل الانزلاق (Momentum)',
    'Glide length': 'طول الانزلاق',
    'Higher = longer, smoother glide': 'أعلى = انزلاق أطول وأنعم',
    'Three-finger gestures': 'إيماءات 3 أصابع',
    'Workspace switching and Overview': 'التنقل بين مساحات العمل والـ Overview',
    '100% = system speed': '100% = سرعة النظام',
    'Could not save: {}".format(e)': 'f"تعذر الحفظ: {e}',
    'Restore default settings?': 'استعادة الإعدادات الافتراضية؟',
    'Cancel': 'إلغاء',
    'Restore': 'استعادة',
    'Defaults restored': 'تمت استعادة الإعدادات الافتراضية',
    'Two-finger speed returns to Mac speed, three-finger to system speed, and acceleration and momentum to their defaults.': 'هترجع سرعة الإصبعين لسرعة الماك، والـ 3 أصابع لسرعة النظام، والتسارع والانزلاق لقيمهم الافتراضية.',
    'Could not save: {}': 'تعذر الحفظ: {}',
}


def _(text):
    """English by default; Arabic when the session language is Arabic."""
    return AR.get(text, text) if IS_ARABIC else text


APP_ID = "io.github.slowscroll.Settings"   # must match the .desktop file name
CONFIG = os.path.expanduser("~/.config/slowscroll.conf")
SERVICE = "slowscroll.service"

# Measured on this MacBook (15" Retina, scale 2x): GNOME scrolls 10.5 px per mm of
# finger travel, the screen shows 4.35 px per mm, so 4.35 / 10.5 = 0.41 makes the
# content move exactly with the fingers at normal speed - the macOS feel.
MAC_SPEED2 = 0.41

DEFAULTS = {
    "SPEED2": MAC_SPEED2, "ACCEL": 0.6, "SPEED3": 1.0, "V_MID": 80, "CURVE": 2.0, "ONSET_MM": 1.2, "ONSET_GAIN": 4.0,
    "RISE_MS": 20, "FALL_MS": 70,
    "MOMENTUM": 1, "GLIDE_MS": 450, "GLIDE_GAIN": 1.0, "GLIDE_MIN": 20, "SETTLE_MS": 200,
    "PAD_WIDTH_MM": 104, "PAD_HEIGHT_MM": 75, "LIFT_SIZE": 130,
}

TEMPLATE = """\
# slowscroll settings - written by "Slowscroll" settings app.
# Saved changes apply within a second, no restart needed. 1.0 = system default speed.

# --- two-finger scrolling ---
SPEED2={SPEED2:g}        # speed at normal finger speed
ACCEL={ACCEL:g}          # acceleration: 0 = constant, 0.9 = strong
V_MID={V_MID:g}          # finger speed (mm/s) where speed equals SPEED2
CURVE={CURVE:g}          # acceleration curve steepness
ONSET_MM={ONSET_MM:g}    # first mm of each scroll is boosted (instant start)
ONSET_GAIN={ONSET_GAIN:g}  # boost at touch-down, fading to normal over ONSET_MM
RISE_MS={RISE_MS:g}      # how quickly acceleration kicks in
FALL_MS={FALL_MS:g}      # how slowly it relaxes

# --- three-finger gestures ---
SPEED3={SPEED3:g}

# --- momentum (glide after lifting, same in every app) ---
MOMENTUM={MOMENTUM:g}    # 1 = on, 0 = off
GLIDE_MS={GLIDE_MS:g}    # glide length
GLIDE_GAIN={GLIDE_GAIN:g}
GLIDE_MIN={GLIDE_MIN:g}
SETTLE_MS={SETTLE_MS:g}

# --- hardware ---
PAD_WIDTH_MM={PAD_WIDTH_MM:g}
PAD_HEIGHT_MM={PAD_HEIGHT_MM:g}
LIFT_SIZE={LIFT_SIZE:g}
"""


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    k, v = (x.strip() for x in line.split("=", 1))
                    if k in cfg:
                        try:
                            cfg[k] = float(v)
                        except ValueError:
                            pass
    except FileNotFoundError:
        pass
    return cfg


def save(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        f.write(TEMPLATE.format(**cfg))
    os.replace(tmp, CONFIG)


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True).stdout.strip()


class SliderRow(Adw.ActionRow):
    """A preferences row with a slider, a live value and a reset button."""

    def __init__(self, title, subtitle, key, lo, hi, step, fmt, on_change, marks=()):
        super().__init__(title=title, subtitle=subtitle)
        self.key, self.fmt, self.on_change, self.step = key, fmt, on_change, step
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        self.scale.set_hexpand(True)
        self.scale.set_size_request(220, -1)
        self.scale.set_draw_value(False)
        self.scale.set_valign(Gtk.Align.CENTER)
        for value, label in marks:
            self.scale.add_mark(value, Gtk.PositionType.BOTTOM, label)
        self.value = Gtk.Label(width_chars=6, xalign=0.5)
        self.value.add_css_class("numeric")
        self.value.add_css_class("dim-label")
        reset = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER,
                           tooltip_text=_("Reset to default"))
        reset.add_css_class("flat")
        reset.connect("clicked", lambda *_: self.set(DEFAULTS[key], notify=True))
        self.add_suffix(self.scale)
        self.add_suffix(self.value)
        self.add_suffix(reset)
        self.scale.connect("value-changed", self._changed)
        self._quiet = False

    def set(self, v, notify=False):
        self._quiet = not notify
        self.scale.set_value(v)
        self._quiet = False
        self.value.set_label(self.fmt(self.scale.get_value()))

    def _changed(self, scale):
        v = round(round(scale.get_value() / self.step) * self.step, 3)
        self.value.set_label(self.fmt(v))
        if not self._quiet:
            self.on_change(self.key, v)


def pct(v):
    return f"{v * 100:.0f}%"


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Slowscroll", default_width=640,
                         default_height=720)
        self.cfg = load()
        self.save_id = 0
        self.toasts = Adw.ToastOverlay()

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Slowscroll",
                                                subtitle=_("Touchpad scrolling")))
        reset_all = Gtk.Button(label=_("Restore defaults"))
        reset_all.add_css_class("destructive-action")
        reset_all.connect("clicked", self.confirm_reset)
        header.pack_end(reset_all)

        page = Adw.PreferencesPage()

        # --- service ----------------------------------------------------------
        g0 = Adw.PreferencesGroup()
        self.svc = Adw.SwitchRow(title=_("Enable Slowscroll"),
                                 subtitle=_("When off, the touchpad uses the system settings"))
        self.svc.add_prefix(Gtk.Image(icon_name="input-touchpad-symbolic"))
        self.svc_handler = self.svc.connect("notify::active", self.toggle_service)
        g0.add(self.svc)
        page.add(g0)

        # --- two fingers --------------------------------------------------------
        g2 = Adw.PreferencesGroup(title=_("Two-finger scrolling"),
                                  description=_("Speed applies to both fingers moving together; pinch-zoom is not affected"))
        self.rows = {}
        self.rows["SPEED2"] = SliderRow(
            _("Speed"), _("Default = Mac speed: content follows your fingers exactly"),
            "SPEED2", 0.1, 1.5, 0.01, pct, self.changed,
            marks=((MAC_SPEED2, _("Mac")), (1.0, _("System"))))
        self.rows["ACCEL"] = SliderRow(
            _("Acceleration"), _("Slow movement = precise, fast flick = farther"), "ACCEL",
            0.0, 0.9, 0.05, pct, self.changed, marks=((0.0, _("Constant")), (0.6, _("Mac"))))
        g2.add(self.rows["SPEED2"])
        g2.add(self.rows["ACCEL"])
        page.add(g2)

        # --- momentum -------------------------------------------------------------
        gm = Adw.PreferencesGroup(title=_("Momentum after lifting fingers"),
                                  description=_("Same feel in every app; touching the touchpad stops it"))
        self.momentum = Adw.SwitchRow(title=_("Enable momentum"))
        self.momentum.connect("notify::active", self.on_momentum)
        self.rows["GLIDE_MS"] = SliderRow(
            _("Glide length"), _("Higher = longer, smoother glide"), "GLIDE_MS", 150, 1200, 25,
            lambda v: f"{v / 1000:.2f}s", self.changed, marks=((450, _("Mac")),))
        gm.add(self.momentum)
        gm.add(self.rows["GLIDE_MS"])
        page.add(gm)

        # --- three fingers --------------------------------------------------------
        g3 = Adw.PreferencesGroup(title=_("Three-finger gestures"),
                                  description=_("Workspace switching and Overview"))
        self.rows["SPEED3"] = SliderRow(
            _("Speed"), _("100% = system speed"), "SPEED3", 0.15, 2.0, 0.01, pct, self.changed,
            marks=((1.0, _("System")),))
        g3.add(self.rows["SPEED3"])
        page.add(g3)


        self.toasts.set_child(page)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.toasts)
        self.set_content(view)

        self.refresh_from_cfg()
        self.refresh_service()
        GLib.timeout_add_seconds(2, self.refresh_service)

    # ---- config -------------------------------------------------------------
    def refresh_from_cfg(self):
        self._loading = True        # showing values is not an edit: don't save
        for key, row in self.rows.items():
            row.set(self.cfg[key])
        self.momentum.set_active(self.cfg["MOMENTUM"] >= 0.5)
        self._loading = False

    def on_momentum(self, row, _):
        self.rows["GLIDE_MS"].set_sensitive(row.get_active() and row.get_sensitive())
        if not getattr(self, "_loading", False):
            self.changed("MOMENTUM", 1 if row.get_active() else 0)

    def changed(self, key, value):
        self.cfg[key] = value
        if self.save_id:
            GLib.source_remove(self.save_id)
        self.save_id = GLib.timeout_add(150, self.flush)

    def flush(self):
        self.save_id = 0
        try:
            save(self.cfg)
        except OSError as e:
            self.toasts.add_toast(Adw.Toast(title=_("Could not save: {}").format(e)))
        return False

    def confirm_reset(self, *_):
        dlg = Adw.AlertDialog(heading=_("Restore default settings?"),
                              body=_("Two-finger speed returns to Mac speed, three-finger to system speed, "
                                   "and acceleration and momentum to their defaults."))
        dlg.add_response("cancel", _("Cancel"))
        dlg.add_response("reset", _("Restore"))
        dlg.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", self.on_reset_response)
        dlg.present(self)

    def on_reset_response(self, _dlg, response):
        if response != "reset":
            return
        self.cfg = dict(DEFAULTS)
        self.refresh_from_cfg()
        self.flush()
        self.toasts.add_toast(Adw.Toast(title=_("Defaults restored")))

    # ---- service ------------------------------------------------------------
    def refresh_service(self):
        active = systemctl("is-active", SERVICE) == "active"
        self.svc.handler_block(self.svc_handler)
        self.svc.set_active(active)
        self.svc.handler_unblock(self.svc_handler)
        for row in list(self.rows.values()) + [self.momentum]:
            row.set_sensitive(active and (row is not self.rows["GLIDE_MS"]
                                          or self.momentum.get_active()))
        return True

    def toggle_service(self, row, _):
        # enable/disable too, so the choice survives a reboot
        systemctl("enable" if row.get_active() else "disable", "--now", SERVICE)
        GLib.timeout_add(600, lambda: self.refresh_service() and False)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.props.active_window or Window(self)
        win.present()


if __name__ == "__main__":
    if IS_ARABIC:
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
    sys.exit(App().run(sys.argv))

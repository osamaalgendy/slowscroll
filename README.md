# slowscroll

Touchpad scroll **speed**, **acceleration** and **momentum** for Linux (libinput),
with a GTK4/libadwaita settings window.

libinput and GNOME have no setting for two-finger scroll speed
([libinput#185](https://gitlab.freedesktop.org/libinput/libinput/issues/185)).
`slowscroll` sits between the touchpad and libinput:

* grabs the touchpad (evdev) and re-emits its events through a virtual touchpad (uinput);
* scales the shared movement of **two fingers** with a smooth speed-dependent
  acceleration curve (slow = precise, fast flick = far);
* scales **three-finger** gestures (workspace switching / Overview) separately;
* adds a **unified momentum glide** after you lift your fingers, so every
  application scrolls the same way (touching the pad stops it, two new fingers catch it);
* boosts the first millimetre of every scroll so it starts as fast as without it.

Pinch-zoom, taps, clicks and single-finger pointer movement are untouched.

## Install

Fedora (once packaged): `sudo dnf install slowscroll`, **log out and back in**
(the udev rule gives the logged-in user access to the touchpad and
`/dev/uinput`), then open **Slowscroll** and turn it on, or run

    systemctl --user enable --now slowscroll.service

From source: install `python3-evdev`, `python3-gobject`, `libadwaita`; copy the
udev rule `70-slowscroll.rules` to `/usr/lib/udev/rules.d/`, `slowscroll.py`
to `~/.local/bin/slowscroll`, `slowscroll.service` to `~/.config/systemd/user/`
(fix `ExecStart`), and run `systemctl --user enable --now slowscroll`.

## Settings

Open **Slowscroll** from the app grid, or edit `~/.config/slowscroll.conf`
(see `slowscroll.conf.example`). Changes apply within a second.
`SPEED2=0.41` is the default: at normal finger speed content moves the same
physical distance as your fingers on a 15" Retina MacBook (an estimate, tune to taste).

## Safety

If the program stops for any reason the real touchpad is released and works
with the system settings again. `systemctl --user stop slowscroll` does the same.

Access to `/dev/uinput` allows creating virtual input devices; the udev rule
grants it to the user at the console (`uaccess`).

## Known limitations

* Only the first touchpad found is handled.
* The virtual touchpad has exactly the real pad's size, so libinput's thumb,
  palm and click-area handling work as without slowscroll. A long glide that
  reaches the pad's edge is handed over to the app's own kinetic scrolling for
  the rest of its distance.
* On non-Apple touchpads libinput may end a touch by pressure before the finger
  leaves the pad; then that app's own kinetic scrolling is used instead of the glide.

## Tested on

MacBookPro11,4 (bcm5974 touchpad), Fedora 44, GNOME Shell 50 (Wayland), libinput 1.31.
Other touchpads should work (multitouch, type-B protocol) but are untested.
Run the unit tests with `python3 tests/test_engine.py slowscroll.py`.

## License

GPL-3.0-or-later. See `LICENSE`.

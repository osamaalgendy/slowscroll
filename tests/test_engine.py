# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Osama Algendy <71908505+osamaalgendy@users.noreply.github.com>
"""Tests for slowscroll. Usage: python3 tests/test_engine.py slowscroll.py"""
import importlib.util
import os
import sys
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location("ss", sys.argv.pop(1))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

PX, PY, SLOT, TID = m.PX, m.PY, m.ABS_MT_SLOT, m.ABS_MT_TRACKING_ID
MAJ, MIN = m.ABS_MT_TOUCH_MAJOR, m.ABS_MT_TOUCH_MINOR
RES = {PX: 97, PY: 93}
LIM = {PX: (-50000, 50000), PY: (-50000, 50000)}


class VDev:
    """Model of the virtual device: applies emitted events like the kernel would."""

    def __init__(self):
        self.slot = 0
        self.touch = {}
        self.keys = {}
        self.frames = 0
        self.events = []

    def emit(self, t, c, v):
        self.events.append((t, c, v))
        if t == 0:
            self.frames += 1
        elif t == 1:
            self.keys[c] = v
        elif c == SLOT:
            self.slot = v
        elif c == TID:
            if v == -1:
                self.touch.pop(self.slot, None)
            else:
                self.touch[self.slot] = {}
        elif t == 3 and 0x30 <= c <= 0x3F:
            self.touch.setdefault(self.slot, {})[c] = v

    def ys(self):
        return {s: t.get(PY) for s, t in self.touch.items()}


class Pad:
    """Drives an Engine with real-touchpad style frames."""

    def __init__(self, size_lift=True, **cfg):
        c = m.load_config("/nonexistent")
        c.update(cfg)
        self.v = VDev()
        self.e = m.Engine(c, RES, LIM, self.v.emit, size_lift=size_lift)
        self.t = 0.0
        self.tid = 100

    def frame(self, ev, dt=0.008):
        self.t += dt
        self.e.frame(ev, self.t)

    def down(self, pts, size=300):
        ev = []
        for slot, (x, y) in pts.items():
            self.tid += 1
            ev += [(3, SLOT, slot), (3, TID, self.tid), (3, PX, x), (3, PY, y),
                   (3, MAJ, size), (3, MIN, size)]
        n = len(self.e.rtouch) + len(pts)
        key = {1: m.BTN_TOOL_FINGER, 2: m.BTN_TOOL_DOUBLETAP, 3: m.BTN_TOOL_TRIPLETAP}.get(n)
        if key:
            ev += [(1, key, 1), (1, m.BTN_TOUCH, 1)]
        self.frame(ev)

    def move(self, pts, extra=()):
        ev = []
        for slot, (x, y) in pts.items():
            ev += [(3, SLOT, slot), (3, PX, x), (3, PY, y)]
        self.frame(ev + list(extra))

    def lift(self, slots):
        ev = []
        for s in slots:
            ev += [(3, SLOT, s), (3, TID, -1)]
        if len(slots) == len(self.e.rtouch):
            ev += [(1, m.BTN_TOOL_DOUBLETAP, 0), (1, m.BTN_TOUCH, 0)]
        self.frame(ev)

    def run_ticks(self, limit=5.0):
        now = time.monotonic()
        self.e.last_tick = now
        end = now + limit
        while self.e.busy() and now < end:
            now += 0.008
            self.e.tick(now)
        return now


def scroll(p, speed_units, n, y0=3000, x=(0, 1000)):
    y = y0
    for _ in range(n):
        y += speed_units
        p.move({0: (x[0], y), 1: (x[1], y)})
    return y


class EngineTests(unittest.TestCase):
    def test_fast_flick_glides_and_ends_lifted(self):
        p = Pad()
        p.down({0: (0, 3000), 1: (1000, 3000)})
        scroll(p, 250, 15)
        p.lift([0, 1])
        self.assertEqual(p.e.mode, m.GLIDE)
        self.assertEqual(len(p.v.touch), 2, "virtual fingers stay down while gliding")
        p.run_ticks()
        self.assertEqual(p.e.mode, m.NORMAL)
        self.assertEqual(p.v.touch, {}, "virtual fingers lifted at the end")
        self.assertEqual(p.v.keys.get(m.BTN_TOUCH), 0)

    def test_slow_lift_no_glide(self):
        p = Pad()
        p.down({0: (0, 3000), 1: (1000, 3000)})
        scroll(p, 3, 30)
        p.lift([0, 1])
        self.assertEqual(p.e.mode, m.NORMAL)
        self.assertEqual(p.v.touch, {})

    def test_symmetric_pinch_no_glide(self):
        p = Pad()
        p.down({0: (0, 3000), 1: (1000, 3000)})
        for k in range(1, 16):
            p.move({0: (-60 * k, 3000), 1: (1000 + 60 * k, 3000)})
        p.lift([0, 1])
        self.assertEqual(p.e.mode, m.NORMAL)

    def test_one_sided_pinch_then_one_finger_lifts_no_glide(self):
        # bug: the pinch check used the finger gap AFTER the lift (1 finger left)
        p = Pad()
        p.down({0: (0, 3000), 1: (3000, 3000)})
        for k in range(1, 16):
            p.move({0: (0, 3000), 1: (3000 - 150 * k, 3000)})   # only finger 1 moves
        p.lift([1])
        self.assertEqual(p.e.mode, m.NORMAL, "pinch-zoom must not start a glide")

    def test_non_apple_small_touch_sizes_do_not_start_glide_mid_scroll(self):
        # bug: Apple's LIFT_SIZE (130) was applied to every touchpad
        p = Pad(size_lift=False)
        p.down({0: (0, 3000), 1: (1000, 3000)}, size=20)
        y = 3000
        for _ in range(15):
            y += 250
            p.move({0: (0, y), 1: (1000, y)}, extra=[(3, SLOT, 0), (3, MAJ, 18)])
        self.assertEqual(p.e.mode, m.NORMAL, "fingers still down: no glide")
        self.assertEqual(len(p.v.touch), 2)

    def test_apple_size_drop_starts_glide(self):
        p = Pad(size_lift=True)
        p.down({0: (0, 3000), 1: (1000, 3000)})
        y = scroll(p, 250, 15)
        p.move({0: (0, y + 250), 1: (1000, y + 250)}, extra=[(3, SLOT, 0), (3, MAJ, 100)])
        self.assertEqual(p.e.mode, m.GLIDE)
        # the shrinking size must not have reached the virtual device
        self.assertTrue(all(t.get(MAJ, 300) >= 130 for t in p.v.touch.values()))

    def test_two_fingers_catch_the_glide_without_jump(self):
        p = Pad()
        p.down({0: (0, 3000), 1: (1000, 3000)})
        scroll(p, 250, 12)
        p.lift([0, 1])
        now = time.monotonic()
        p.e.last_tick = now
        for _ in range(10):
            now += 0.008
            p.e.tick(now)
        before = p.v.ys()
        p.down({3: (0, 500)})
        self.assertEqual(p.e.mode, m.SETTLE)
        p.down({4: (900, 500)})
        self.assertEqual(p.e.mode, m.NORMAL)
        self.assertEqual(p.v.ys(), before, "no jump when catching")
        p.move({3: (0, 520), 4: (900, 520)})
        moved = [p.v.ys()[s] - before[s] for s in before]
        self.assertTrue(all(0 < d <= 20 for d in moved), moved)

    def test_one_finger_after_glide_gets_pointer_back(self):
        p = Pad()
        p.down({0: (0, 3000), 1: (1000, 3000)})
        scroll(p, 250, 12)
        p.lift([0, 1])
        p.down({0: (100, 800)})
        self.assertEqual(p.e.mode, m.SETTLE)
        p.run_ticks()
        self.assertEqual(p.e.mode, m.NORMAL)
        self.assertEqual(len(p.v.touch), 1)
        p.move({0: (150, 800)})
        self.assertEqual(list(p.v.touch.values())[0][PX], 150, "1 finger moves 1:1")

    def test_three_fingers_use_speed3(self):
        p = Pad(SPEED3=0.5)
        p.down({0: (0, 3000), 1: (1000, 3000), 2: (2000, 3000)})
        for k in range(1, 11):
            p.move({0: (0, 3000 + 100 * k), 1: (1000, 3000 + 100 * k), 2: (2000, 3000 + 100 * k)})
        self.assertEqual(sorted(p.v.ys().values()), [3500, 3500, 3500])

    def test_finger_count_changes_keep_positions_continuous(self):
        p = Pad()
        p.down({0: (0, 3000)})
        p.move({0: (0, 3100)})
        p.down({1: (1000, 3100)})
        y = scroll(p, 3, 30, y0=3100)   # slow: no glide on lift
        before = p.v.ys()[0]
        p.lift([1])
        self.assertEqual(p.v.ys()[0], before, "remaining finger does not jump")
        p.move({0: (0, y + 50)})
        self.assertEqual(p.v.ys()[0], before + 50, "single finger is 1:1 again")

    def test_resync_after_dropped_events_clears_ghost_fingers(self):
        # bug: SYN_DROPPED was ignored, a missed lift left a ghost finger forever
        p = Pad()
        p.down({0: (0, 3000), 1: (1000, 3000)})
        p.e.resync(active_keys=[m.BTN_LEFT])
        self.assertEqual(p.v.touch, {}, "all virtual fingers lifted")
        self.assertEqual(p.e.rtouch, {})
        self.assertEqual(p.e.rkeys, {m.BTN_LEFT: 1})
        # events for the old touches are ignored, a new touch works normally
        p.move({0: (50, 3050)})
        self.assertEqual(p.v.touch, {})
        p.down({2: (10, 20)})
        self.assertEqual(len(p.v.touch), 1)

    def test_resync_during_glide(self):
        p = Pad()
        p.down({0: (0, 3000), 1: (1000, 3000)})
        scroll(p, 250, 12)
        p.lift([0, 1])
        self.assertEqual(p.e.mode, m.GLIDE)
        p.e.resync()
        self.assertEqual(p.e.mode, m.NORMAL)
        self.assertEqual(p.v.touch, {})

    def test_alloc_respects_max_slot(self):
        p = Pad()
        p.e.max_slot = 2
        p.down({7: (0, 0)})
        self.assertLessEqual(max(p.e.vslot_of.values()), 2)

    def test_start_mid_touch_is_ignored(self):
        p = Pad()
        p.move({0: (5, 5)})          # touch began before the daemon started
        self.assertEqual(p.v.touch, {})
        p.lift([0])
        p.down({0: (1, 2)})
        self.assertEqual(len(p.v.touch), 1)

    def test_config_clamping(self):
        c = m.load_config("/nonexistent")
        self.assertEqual(c["SPEED2"], 0.41)
        conf = os.path.join(tempfile.mkdtemp(), "t.conf")
        with open(conf, "w") as f:
            f.write("SPEED2=99\nACCEL=-1\nGLIDE_MS=1\nbad line\nSPEED3=abc\n")
        c = m.load_config(conf)
        self.assertEqual((c["SPEED2"], c["ACCEL"], c["GLIDE_MS"], c["SPEED3"]), (3.0, 0.0, 20.0, 1.0))


class DetectTests(unittest.TestCase):
    def test_find_touchpads_rejects_touchscreens(self):
        from evdev import ecodes as e

        class Info:
            vendor = 1

        class Dev:
            def __init__(self, name, props):
                self.name, self._props, self.info, self.closed = name, props, Info(), False

            def capabilities(self):
                return {e.EV_ABS: [(e.ABS_MT_POSITION_X, None)], e.EV_KEY: [e.BTN_TOOL_FINGER]}

            def input_props(self):
                return self._props

            def close(self):
                self.closed = True

        devs = {"/a": Dev("touchscreen", [e.INPUT_PROP_DIRECT]),
                "/b": Dev("pad (slowscroll)", [e.INPUT_PROP_POINTER]),
                "/c": Dev("real pad", [e.INPUT_PROP_POINTER, e.INPUT_PROP_BUTTONPAD])}
        import evdev
        orig = (evdev.list_devices, evdev.InputDevice)
        evdev.list_devices = lambda: list(devs)
        evdev.InputDevice = lambda p: devs[p]
        try:
            found = m.find_touchpads()
        finally:
            evdev.list_devices, evdev.InputDevice = orig
        self.assertEqual([d.name for d in found], ["real pad"])

    def test_glide_room(self):
        class Info:
            vendor = m.APPLE

        class Dev:
            info = Info()

        orig = m.click_method
        try:
            for method, vendor, want in (("default", m.APPLE, 400), ("fingers", 1, 400),
                                         ("areas", m.APPLE, 0), ("default", 1, 0)):
                m.click_method = lambda method=method: method
                Dev.info.vendor = vendor
                self.assertEqual(m.glide_room_mm(Dev()), want, (method, vendor))
        finally:
            m.click_method = orig


if __name__ == "__main__":
    unittest.main(verbosity=1)

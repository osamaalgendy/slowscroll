#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Osama Algendy <71908505+osamaalgendy@users.noreply.github.com>
"""slowscroll - macOS-like two-finger scrolling with unified momentum.

Grabs the real touchpad and re-emits events through a virtual one:

* Two-finger movement is scaled by SPEED2 and a smooth speed-dependent
  acceleration curve (slow = precise, fast flick = far). Three-finger gestures
  are scaled by SPEED3. Only the fingers' shared (centroid) movement is scaled,
  so pinch-zoom keeps its normal speed.
* Momentum: when you lift your fingers after a flick, the virtual fingers stay
  "down" and keep gliding with an exponential slowdown, then rest still before
  lifting. Apps therefore see one ordinary touchpad scroll that ends at zero
  speed, so their own (inconsistent) kinetic scrolling never kicks in - the
  glide feels the same in every app. Touching the pad stops the glide; putting
  two fingers down catches it and continues scrolling. The virtual touchpad has
  the real pad's size (so libinput's palm and thumb detection keep working); a
  glide that reaches its edge is handed over to the app's own kinetic scrolling.

Settings live in a KEY=VALUE file that is re-read automatically on change.
"""
import argparse
import collections
import errno
import math
import os
import select
import signal
import sys
import time

VERSION = "1.0.1"

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT, SYN_DROPPED = 0, 3
BTN_LEFT = 0x110
BTN_TOUCH = 0x14A
BTN_TOOL_FINGER = 0x145
BTN_TOOL_QUINTTAP = 0x148
BTN_TOOL_DOUBLETAP = 0x14D
BTN_TOOL_TRIPLETAP = 0x14E
BTN_TOOL_QUADTAP = 0x14F
TOOL_KEYS = (BTN_TOOL_FINGER, BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP,
             BTN_TOOL_QUADTAP, BTN_TOOL_QUINTTAP)
ABS_X, ABS_Y = 0x00, 0x01
ABS_MT_SLOT = 0x2F
ABS_MT_TOUCH_MAJOR, ABS_MT_TOUCH_MINOR = 0x30, 0x31
ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x35, 0x36
ABS_MT_TRACKING_ID = 0x39
PX, PY = ABS_MT_POSITION_X, ABS_MT_POSITION_Y
MT_FIRST, MT_LAST = 0x2F, 0x3F

DEFAULTS = {
    # --- two-finger speed curve -------------------------------------------
    # 0.41 = "Mac speed" on a 15" Retina MacBook: at normal finger speed the content
    # moves the same physical distance as your fingers (GNOME moves it ~2.4x)
    "SPEED2": 0.41,      # two-finger scroll speed at normal finger speed (1.0 = system)
    "ACCEL": 0.6,        # acceleration: 0 = constant speed, 0.9 = strong
    "SPEED3": 1.0,       # three-finger gesture speed (1.0 = system)
    "V_MID": 80.0,       # finger speed (mm/s) where two-finger gain equals SPEED2
    "CURVE": 2.0,        # S-curve steepness (1 = gentle, 3 = sharp)
    "ONSET_MM": 1.2,     # first mm of each scroll is boosted so libinput starts at once
    "ONSET_GAIN": 4.0,   # boost at touch-down, fading to the normal curve over ONSET_MM
    "RISE_MS": 20.0,     # how fast acceleration reacts when you speed up
    "FALL_MS": 70.0,     # how slowly it relaxes when you slow down
    # --- momentum (glide after lifting) -----------------------------------
    "MOMENTUM": 1.0,     # 1 = on, 0 = off (apps do their own kinetic scrolling)
    "GLIDE_MS": 450.0,   # glide length: time for speed to drop to ~37%
    "GLIDE_GAIN": 1.0,   # multiplier on the speed you lift with
    "GLIDE_MIN": 20.0,   # min lift speed (mm/s, after gain) that starts a glide
    "SETTLE_MS": 200.0,  # rest time before the virtual fingers lift
    # --- hardware -----------------------------------------------------------
    "PAD_WIDTH_MM": 104.0,
    "PAD_HEIGHT_MM": 75.0,
    "LIFT_SIZE": 130.0,  # libinput's touch-end size for Apple pads (quirk); Apple only
}


def load_config(path):
    cfg = dict(DEFAULTS)
    try:
        with open(path) as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if "=" not in line:
                    continue
                k, v = (x.strip() for x in line.split("=", 1))
                if k in cfg:
                    try:
                        cfg[k] = float(v)
                    except ValueError:
                        print(f"slowscroll: ignoring bad value {k}={v}", flush=True)
    except FileNotFoundError:
        pass
    cfg["SPEED2"] = min(3.0, max(0.05, cfg["SPEED2"]))
    cfg["SPEED3"] = min(3.0, max(0.05, cfg["SPEED3"]))
    cfg["ACCEL"] = min(0.95, max(0.0, cfg["ACCEL"]))
    cfg["V_MID"] = max(1.0, cfg["V_MID"])
    cfg["CURVE"] = max(0.5, cfg["CURVE"])
    cfg["GLIDE_MS"] = max(20.0, cfg["GLIDE_MS"])
    cfg["SETTLE_MS"] = max(0.0, cfg["SETTLE_MS"])
    return cfg


NORMAL, GLIDE, SETTLE = "normal", "glide", "settle"


class Engine:
    """Turns real touchpad frames into virtual touchpad frames."""

    def __init__(self, cfg, res, vlimits, emit, size_lift=False, max_slot=15):
        self.res = res              # {PX: units/mm, PY: units/mm}
        self.vlimits = vlimits      # virtual position ranges {PX: (lo, hi), PY: ...}
        self.emit = emit            # emit(type, code, value)
        # Apple touchpads end a touch in libinput when its size drops below
        # LIFT_SIZE; other touchpads use other units, so only check it on Apple.
        self.size_lift = size_lift
        self.max_slot = max_slot
        self.configure(cfg)
        # real device state
        self.rslot = 0
        self.rtouch = {}            # real slot -> {code: value} (active touches only)
        self.rkeys = {}
        self.rabs = {}              # non-MT abs axes
        # virtual device state
        self.vslot_of = {}          # real slot -> virtual slot
        self.vcur = None            # currently selected virtual slot
        self.vpos = {}              # virtual slot -> [x, y] last emitted ints
        self.off = {}               # real slot -> [dx, dy] continuity offset
        self.G = [0.0, 0.0]         # shared extra movement while 2 fingers scroll
        self.mode = NORMAL
        # two-finger session
        self.speed = 0.0
        self.last_t = None
        self.hist = collections.deque(maxlen=32)
        self.sep0 = None
        self.travel = 0.0
        self.onset_left = self.cfg["ONSET_MM"]
        # glide state
        self.phantom = {}           # virtual slot -> [x, y] floats
        self.vel = [0.0, 0.0]       # units/s
        self.last_tick = 0.0
        self.settle_until = 0.0
        self.fresh = set()          # real slots touched after the glide began

    def configure(self, cfg):
        self.cfg = cfg

    # ---- helpers -----------------------------------------------------------
    def mm(self, dx, dy):
        return math.hypot(dx / self.res[PX], dy / self.res[PY])

    def curve(self, v):
        c = self.cfg
        x = (v / c["V_MID"]) ** c["CURVE"]
        s = x / (1.0 + x)               # 0 when slow, 0.5 at V_MID, -> 1 when fast
        return c["SPEED2"] * (1.0 + c["ACCEL"] * (2.0 * s - 1.0))

    def select(self, vs):
        if self.vcur != vs:
            self.emit(EV_ABS, ABS_MT_SLOT, vs)
            self.vcur = vs

    def alloc(self, rs):
        used = set(self.vslot_of.values()) | set(self.phantom)
        free = [s for s in range(self.max_slot + 1) if s not in used]
        vs = rs if rs not in used and rs <= self.max_slot else (free[0] if free else 0)
        self.vslot_of[rs] = vs
        return vs

    def raw_pos(self, rs):
        t = self.rtouch[rs]
        return t.get(PX, 0), t.get(PY, 0)

    def out_pos(self, rs, scaled):
        x, y = self.raw_pos(rs)
        d = self.off.get(rs, [0.0, 0.0])
        g = self.G if scaled else (0.0, 0.0)
        lo_x, hi_x = self.vlimits[PX]
        lo_y, hi_y = self.vlimits[PY]
        return (max(lo_x, min(hi_x, x + d[0] + g[0])),
                max(lo_y, min(hi_y, y + d[1] + g[1])))

    def centroid(self, slots, fn):
        pts = [fn(s) for s in slots]
        n = max(1, len(pts))
        return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n

    def separation(self, touches=None):
        touches = self.rtouch if touches is None else touches
        a, b = list(touches)[:2]
        (ax, ay) = touches[a].get(PX, 0), touches[a].get(PY, 0)
        (bx, by) = touches[b].get(PX, 0), touches[b].get(PY, 0)
        return self.mm(ax - bx, ay - by)

    def reset_session(self):
        self.speed = 0.0
        self.last_t = None
        self.hist.clear()
        self.sep0 = self.separation() if len(self.rtouch) == 2 else None
        self.travel = 0.0
        self.onset_left = self.cfg["ONSET_MM"]

    def fold_G(self):
        for rs in self.rtouch:
            d = self.off.setdefault(rs, [0.0, 0.0])
            d[0] += self.G[0]
            d[1] += self.G[1]
        self.G = [0.0, 0.0]

    # ---- parsing -----------------------------------------------------------
    def apply_real(self, events):
        """Update real state. Returns (started, ended, deltas, lifting, other)."""
        started, ended, lifting = [], [], set()
        deltas = collections.defaultdict(lambda: [0, 0])
        other = []                  # (kind, slot_or_None, code, value) in order
        low = self.cfg["LIFT_SIZE"] if self.size_lift else None
        for etype, code, value in events:
            if etype == EV_ABS and code == ABS_MT_SLOT:
                self.rslot = value
            elif etype == EV_ABS and code == ABS_MT_TRACKING_ID:
                rs = self.rslot
                if value == -1:
                    if rs in self.rtouch:
                        del self.rtouch[rs]
                        ended.append(rs)
                else:
                    self.rtouch[rs] = {ABS_MT_TRACKING_ID: value}
                    started.append(rs)
                    other.append(("mt", rs, code, value))
            elif etype == EV_ABS and MT_FIRST <= code <= MT_LAST:
                rs = self.rslot
                t = self.rtouch.get(rs)
                if t is None:       # touch began before we started; ignore it
                    continue
                if code in (PX, PY):
                    if code in t and rs not in started:
                        deltas[rs][code == PY] += value - t[code]
                    t[code] = value
                else:
                    t[code] = value
                    if (low is not None and value < low
                            and code in (ABS_MT_TOUCH_MAJOR, ABS_MT_TOUCH_MINOR)):
                        lifting.add(rs)
                    other.append(("mt", rs, code, value))
            elif etype == EV_KEY:
                self.rkeys[code] = value
                other.append(("key", None, code, value))
            elif etype == EV_ABS:
                self.rabs[code] = value
                other.append(("abs", None, code, value))
            else:
                other.append(("raw", etype, code, value))
        return started, ended, deltas, lifting, other

    # ---- normal mode ---------------------------------------------------------
    def frame(self, events, t):
        if self.mode != NORMAL:
            return self.frame_held(events)

        before = set(self.rtouch)
        two_before = len(before) == 2
        snapshot = {rs: dict(v) for rs, v in self.rtouch.items()}
        started, ended, deltas, lifting, other = self.apply_real(events)

        # Fingers leaving a two-finger scroll: start a glide instead of lifting.
        if (two_before and self.cfg["MOMENTUM"] >= 0.5 and not started
                and (ended or lifting & before) and self.is_scroll(snapshot)):
            vx, vy = self.lift_velocity(t)
            g = self.cfg["GLIDE_GAIN"]
            if self.mm(vx, vy) * g >= self.cfg["GLIDE_MIN"]:
                self.start_glide(before, vx * g, vy * g)
                return

        for rs in ended:
            vs = self.vslot_of.pop(rs, None)
            self.off.pop(rs, None)
            if vs is not None:
                self.select(vs)
                self.emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
                self.vpos.pop(vs, None)
        now_set = set(self.rtouch)
        two = len(now_set) == 2
        scaled = len(now_set) in (2, 3)
        if now_set != before:
            self.fold_G()           # keep continuing fingers where they are
        for rs in started:
            self.alloc(rs)
            self.off[rs] = [0.0, 0.0]
        if now_set != before:
            self.reset_session()
        elif len(now_set) == 3:
            dcx = sum(deltas[s][0] for s in now_set) / 3.0
            dcy = sum(deltas[s][1] for s in now_set) / 3.0
            self.G[0] += (self.cfg["SPEED3"] - 1.0) * dcx
            self.G[1] += (self.cfg["SPEED3"] - 1.0) * dcy
        elif two:
            dcx = sum(deltas[s][0] for s in now_set) / 2.0
            dcy = sum(deltas[s][1] for s in now_set) / 2.0
            dist = self.mm(dcx, dcy)
            if self.last_t is not None:
                dt = t - self.last_t
                if 0 < dt < 0.1:
                    inst = dist / max(dt, 0.002)
                    tau = (self.cfg["RISE_MS"] if inst > self.speed else self.cfg["FALL_MS"]) / 1000
                    self.speed += (inst - self.speed) * (1 - math.exp(-dt / max(tau, 1e-3)))
                elif dt >= 0.1:
                    self.speed = 0.0
            self.last_t = t
            if self.onset_left > 0:
                # let libinput recognise the scroll as fast as without us
                # boost that fades into the normal curve, so there is no jump
                frac = self.onset_left / max(self.cfg["ONSET_MM"], 1e-6)
                base = self.curve(self.speed)
                gain = base + (self.cfg["ONSET_GAIN"] - base) * frac
                self.onset_left -= dist
            else:
                gain = self.curve(self.speed)
            self.G[0] += (gain - 1.0) * dcx
            self.G[1] += (gain - 1.0) * dcy
            self.travel += dist * gain

        # forward non-position events with slot remapping
        for kind, a, code, value in other:
            if kind == "mt":
                if a not in self.rtouch:
                    continue
                self.select(self.vslot_of[a])
                self.emit(EV_ABS, code, value)
            elif kind == "raw":
                self.emit(a, code, value)
            else:
                self.emit(EV_KEY if kind == "key" else EV_ABS, code, value)

        # positions for every active finger
        for rs in sorted(self.rtouch):
            if PX not in self.rtouch[rs] or PY not in self.rtouch[rs]:
                continue
            vs = self.vslot_of.get(rs)
            if vs is None:
                continue
            ox, oy = self.out_pos(rs, scaled)
            p = [int(round(ox)), int(round(oy))]
            old = self.vpos.get(vs)
            if old != p:
                self.select(vs)
                if old is None or old[0] != p[0]:
                    self.emit(EV_ABS, PX, p[0])
                if old is None or old[1] != p[1]:
                    self.emit(EV_ABS, PY, p[1])
                self.vpos[vs] = p
        self.emit(EV_SYN, SYN_REPORT, 0)

        if two and now_set == before:
            cx, cy = self.centroid(now_set, lambda s: self.out_pos(s, True))
            self.hist.append((t, cx, cy))

    def is_scroll(self, touches):
        """True unless the two fingers mostly pinched/spread (positions before lift)."""
        if self.sep0 is None or len(touches) < 2:
            return True
        return abs(self.separation(touches) - self.sep0) < max(3.0, 0.7 * self.travel)

    def lift_velocity(self, t):
        h = [p for p in self.hist if p[0] >= t - 0.07]
        if len(h) < 3 or t - h[-1][0] > 0.04:
            return 0.0, 0.0
        n = len(h)
        mt = sum(p[0] for p in h) / n
        den = sum((p[0] - mt) ** 2 for p in h)
        if den <= 0:
            return 0.0, 0.0
        vx = sum((p[0] - mt) * p[1] for p in h) / den
        vy = sum((p[0] - mt) * p[2] for p in h) / den
        return vx, vy

    # ---- glide -------------------------------------------------------------
    def start_glide(self, slots, vx, vy):
        # phantom fingers continue from where the virtual fingers are now
        self.phantom = {}
        for rs in slots:
            vs = self.vslot_of.get(rs)
            if vs is not None and vs in self.vpos:
                self.phantom[vs] = [float(c) for c in self.vpos[vs]]
        self.vslot_of.clear()
        self.off.clear()
        self.G = [0.0, 0.0]
        self.vel = [vx, vy]
        self.fresh = set()
        self.mode = GLIDE
        self.last_tick = time.monotonic()

    def frame_held(self, events):
        started, _, _, _, other = self.apply_real(events)
        self.fresh |= set(started)
        self.fresh &= set(self.rtouch)
        clicked = any(k == "key" and c == BTN_LEFT and v == 1 for k, _, c, v in other)
        if started or clicked:
            if self.mode == GLIDE:      # touching the pad stops the glide
                self.mode = SETTLE
                self.settle_until = time.monotonic() + self.cfg["SETTLE_MS"] / 1000
            if (len(self.rtouch) == 2 and self.fresh == set(self.rtouch)
                    and not self.rkeys.get(BTN_LEFT) and len(self.phantom) == 2):
                self.catch_glide()

    def catch_glide(self):
        """Two new fingers landed: they take over the phantom fingers seamlessly."""
        for rs, vs in zip(sorted(self.rtouch), sorted(self.phantom)):
            self.vslot_of[rs] = vs
            px, py = self.phantom[vs]
            rx, ry = self.raw_pos(rs)
            self.off[rs] = [px - rx, py - ry]
            for code, value in self.rtouch[rs].items():
                if code not in (PX, PY, ABS_MT_TRACKING_ID):
                    self.select(vs)
                    self.emit(EV_ABS, code, value)
        self.phantom = {}
        self.sync_keys_abs()
        self.emit(EV_SYN, SYN_REPORT, 0)
        self.mode = NORMAL
        self.reset_session()
        self.onset_left = 0.0       # libinput is already scrolling

    def sync_keys_abs(self):
        for code, value in self.rkeys.items():
            self.emit(EV_KEY, code, value)
        for code, value in self.rabs.items():
            self.emit(EV_ABS, code, value)

    def tick(self, now):
        if self.mode == GLIDE:
            dt = min(0.05, max(0.0, now - self.last_tick))
            self.last_tick = now
            k = math.exp(-dt / (self.cfg["GLIDE_MS"] / 1000))
            self.vel = [v * k for v in self.vel]
            dx, dy = self.vel[0] * dt, self.vel[1] * dt
            if self.near_edge(dx, dy):
                # no room left on the pad: lift now, while still moving, so the
                # app's own kinetic scrolling carries the rest of the glide
                self.finish_glide()
                return
            for vs, p in self.phantom.items():
                p[0] += dx
                p[1] += dy
                q = [int(round(p[0])), int(round(p[1]))]
                old = self.vpos.get(vs)
                if old != q:
                    self.select(vs)
                    if old is None or old[0] != q[0]:
                        self.emit(EV_ABS, PX, q[0])
                    if old is None or old[1] != q[1]:
                        self.emit(EV_ABS, PY, q[1])
                    self.vpos[vs] = q
            self.emit(EV_SYN, SYN_REPORT, 0)
            if self.mm(*self.vel) < 3.0:
                self.mode = SETTLE
                self.settle_until = now + self.cfg["SETTLE_MS"] / 1000
        elif self.mode == SETTLE and now >= self.settle_until:
            self.finish_glide()

    def near_edge(self, dx, dy, guard_mm=2.0):
        """Would this glide step bring a phantom finger within guard_mm of the pad edge?"""
        for p in self.phantom.values():
            for i, axis, d in ((0, PX, dx), (1, PY, dy)):
                lo, hi = self.vlimits[axis]
                g = guard_mm * self.res[axis]
                if not lo + g <= p[i] + d <= hi - g:
                    return True
        return False

    def finish_glide(self):
        for vs in self.phantom:
            self.select(vs)
            self.emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
            self.vpos.pop(vs, None)
        for code in TOOL_KEYS + (BTN_TOUCH,):
            self.emit(EV_KEY, code, 0)
        self.emit(EV_SYN, SYN_REPORT, 0)
        self.phantom = {}
        # hand over any fingers that are on the pad right now as fresh touches
        for rs in sorted(self.rtouch):
            vs = self.alloc(rs)
            self.off[rs] = [0.0, 0.0]
            self.select(vs)
            for code, value in sorted(self.rtouch[rs].items(),
                                      key=lambda kv: kv[0] != ABS_MT_TRACKING_ID):
                self.emit(EV_ABS, code, value)
            if PX in self.rtouch[rs] and PY in self.rtouch[rs]:
                self.vpos[vs] = list(self.raw_pos(rs))
        if self.rtouch or self.rkeys.get(BTN_LEFT):
            self.sync_keys_abs()
            self.emit(EV_SYN, SYN_REPORT, 0)
        self.mode = NORMAL
        self.reset_session()

    def busy(self):
        return self.mode != NORMAL

    def resync(self, active_keys=()):
        """The kernel dropped events (SYN_DROPPED): our view of the fingers may be
        wrong, so lift every virtual finger and start clean. Fingers that are on
        the pad right now are ignored until they lift, like at startup."""
        for vs in set(self.vslot_of.values()) | set(self.phantom) | set(self.vpos):
            self.select(vs)
            self.emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
        for code in TOOL_KEYS + (BTN_TOUCH,):
            self.emit(EV_KEY, code, 0)
        self.emit(EV_SYN, SYN_REPORT, 0)
        self.rtouch.clear()
        self.vslot_of.clear()
        self.vpos.clear()
        self.off.clear()
        self.phantom = {}
        self.G = [0.0, 0.0]
        self.rkeys = {k: 1 for k in active_keys if k not in TOOL_KEYS + (BTN_TOUCH,)}
        self.mode = NORMAL
        self.reset_session()


def find_touchpads():
    import evdev
    from evdev import ecodes
    found = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities()
        abs_codes = [c if isinstance(c, int) else c[0] for c in caps.get(ecodes.EV_ABS, [])]
        keys = caps.get(ecodes.EV_KEY, [])
        props = dev.input_props()
        if (ecodes.ABS_MT_POSITION_X in abs_codes and ecodes.BTN_TOOL_FINGER in keys
                and ecodes.INPUT_PROP_POINTER in props
                and ecodes.INPUT_PROP_DIRECT not in props      # not a touchscreen
                and "slowscroll" not in dev.name.lower()):
            found.append(dev)
        else:
            dev.close()
    return found


def describe(cfg):
    return " ".join(f"{k}={v:g}" for k, v in cfg.items())


APPLE = 0x05AC


def build_virtual(dev, cfg):
    """Virtual touchpad: same device and size, with an explicit resolution.

    It must not be larger than the real pad: libinput places its palm-edge and
    thumb zones relative to the declared size, so an enlarged pad moves them off
    the physical surface and resting palms start moving the pointer."""
    from evdev import ecodes, AbsInfo, UInput
    caps = dev.capabilities()
    caps.pop(ecodes.EV_SYN, None)
    caps.pop(ecodes.EV_FF, None)
    info = dict(caps[ecodes.EV_ABS])
    size = {PX: cfg["PAD_WIDTH_MM"], PY: cfg["PAD_HEIGHT_MM"]}
    res, vlimits = {}, {}
    for axis, st in ((PX, ABS_X), (PY, ABS_Y)):
        i = info[axis]
        # same resolution libinput derives from its size hint, so speeds stay identical
        res[axis] = i.resolution or max(1, int((i.max - i.min) / size[axis]))
        vlimits[axis] = (i.min, i.max)
        for code in (axis, st):
            if code in info:
                j = info[code]
                info[code] = AbsInfo(j.value, j.min, j.max, j.fuzz, j.flat, res[axis])
    caps[ecodes.EV_ABS] = list(info.items())
    max_slot = info[ABS_MT_SLOT].max if ABS_MT_SLOT in info else 0
    ui = UInput(caps, name=dev.name + " (slowscroll)", input_props=dev.input_props(),
                vendor=dev.info.vendor, product=dev.info.product,
                version=dev.info.version, bustype=dev.info.bustype)
    return ui, res, vlimits, max_slot


def run(dev, config_path):
    def mtime():
        try:
            return os.stat(config_path).st_mtime
        except OSError:
            return None

    cfg_mtime = mtime()
    cfg = load_config(config_path)
    ui, res, vlimits, max_slot = build_virtual(dev, cfg)
    eng = Engine(cfg, res, vlimits, ui.write,
                 size_lift=dev.info.vendor == APPLE, max_slot=max_slot)
    next_check = 0.0
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    buf = []
    dropping = False
    try:
        dev.grab()
        print(f"slowscroll {VERSION}: {dev.name} ({dev.path}) res={res[PX]}x{res[PY]}/mm "
              f"{describe(cfg)}", flush=True)
        while not stop:
            timeout = 0.008 if eng.busy() else 0.5
            r, _, _ = select.select([dev.fd], [], [], timeout)
            now = time.monotonic()
            if now >= next_check:
                next_check = now + 0.5
                m = mtime()
                if m != cfg_mtime:
                    cfg_mtime = m
                    eng.configure(load_config(config_path))
                    print(f"slowscroll: reloaded {describe(eng.cfg)}", flush=True)
            if r:
                for ev in dev.read():
                    if ev.type == EV_SYN and ev.code == SYN_DROPPED:
                        dropping = True       # discard until the next SYN_REPORT
                        buf = []
                    elif ev.type == EV_SYN and ev.code == SYN_REPORT:
                        if dropping:
                            dropping = False
                            eng.resync(dev.active_keys())
                            print("slowscroll: events dropped, resynced", flush=True)
                        else:
                            eng.frame(buf, ev.timestamp())
                        buf = []
                    elif ev.type != EV_SYN and not dropping:
                        buf.append((ev.type, ev.code, ev.value))
            if eng.busy():
                eng.tick(time.monotonic())
    except KeyboardInterrupt:
        pass
    except OSError as e:
        if e.errno != errno.ENODEV:
            raise
        print("slowscroll: touchpad disappeared (suspend/unplug?), exiting", flush=True)
        sys.exit(1)               # systemd restarts us once the touchpad is back
    finally:
        try:
            dev.ungrab()
        except OSError:
            pass
        ui.close()
        print("slowscroll: released touchpad", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", default=os.path.expanduser("~/.config/slowscroll.conf"),
                   help="KEY=VALUE settings file, re-read on change")
    p.add_argument("--device", help="evdev path (default: auto-detect)")
    p.add_argument("--list", action="store_true", help="list detected touchpads and exit")
    p.add_argument("--curve", action="store_true", help="print the gain curve and exit")
    p.add_argument("--version", action="version", version=f"slowscroll {VERSION}")
    args = p.parse_args()

    if args.curve:
        eng = Engine(load_config(args.config), {PX: 1, PY: 1}, {}, lambda *a: None)
        for v in (5, 10, 20, 40, 60, 80, 100, 150, 200, 300, 400, 600):
            g = eng.curve(v)
            print(f"{v:4d} mm/s  gain {g:.2f}  {'#' * int(g * 50)}")
        return

    try:
        import evdev
    except ImportError:
        sys.exit("python-evdev missing: sudo dnf install python3-evdev")

    pads = [evdev.InputDevice(args.device)] if args.device else find_touchpads()
    if args.list:
        for d in pads:
            print(d.path, d.name)
        return
    if not pads:
        sys.exit("no touchpad found (try --list; after installing, log out and in "
                 "so the udev rule gives you access)")
    try:
        run(pads[0], args.config)
    except PermissionError as e:
        sys.exit(f"permission denied ({e}); log out and in after installing so the "
                 "udev rule gives you access to the touchpad and /dev/uinput")


if __name__ == "__main__":
    main()

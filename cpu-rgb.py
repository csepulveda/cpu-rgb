#!/usr/bin/env python3
"""cpu-rgb: drive your PC's RGB lighting from CPU load (or CPU temperature) through OpenRGB.

How it works
------------
* Every ``poll_seconds`` it samples a metric:
    - ``source = "cpu"``  -> total CPU utilisation in % (0-100), from /proc/stat deltas
    - ``source = "temp"`` -> a hwmon temperature in degrees C (e.g. k10temp/Tctl on AMD,
                            coretemp/"Package id 0" on Intel)
* The value is smoothed with an exponential moving average (``smoothing``).
* A colour is interpolated linearly between the anchor points of ``gradient``.
* The colour is quantised (``quantize``) and, only when it actually changes, pushed to
  OpenRGB by calling the ``openrgb`` CLI as a *client* of a locally running OpenRGB SDK
  server. Using the server avoids re-detecting hardware on every update.

Configuration is a JSON file (default /etc/cpu-rgb.conf, override with --config or the
CPU_RGB_CONF environment variable). Send SIGHUP (``systemctl reload cpu-rgb``) to reload it.
"""
import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import time

DEFAULT_CONF = os.environ.get("CPU_RGB_CONF", "/etc/cpu-rgb.conf")

DEFAULTS = {
    "source": "cpu",
    "poll_seconds": 2.0,
    "smoothing": 0.4,
    "min_update_seconds": 3.0,
    "quantize": 8,
    "sensor_name": "k10temp",
    "sensor_label": "Tctl",
    "openrgb": ["/usr/bin/openrgb", "--client", "127.0.0.1:6742", "--nodetect"],
    "devices": [0],
    "mode": "static",
    "gradient": [
        [0, "FFFFFF"],
        [3, "FFFFFF"],
        [10, "0000FF"],
        [25, "00FFFF"],
        [40, "00FF00"],
        [60, "FFFF00"],
        [80, "FF8000"],
        [100, "FF0000"],
    ],
}


def log(msg):
    print(msg, flush=True)


def load_conf(path):
    conf = dict(DEFAULTS)
    try:
        with open(path) as f:
            conf.update(json.load(f))
    except FileNotFoundError:
        log(f"no config at {path}, using built-in defaults")
    except Exception as e:  # noqa: BLE001
        log(f"error reading {path}: {e}; using built-in defaults")
    if "device" in conf and "devices" not in conf:  # backwards compat
        conf["devices"] = [conf["device"]]
    if isinstance(conf["devices"], int):
        conf["devices"] = [conf["devices"]]
    conf["gradient"] = sorted(((float(v), c.upper()) for v, c in conf["gradient"]), key=lambda x: x[0])
    return conf


# --------------------------------------------------------------------------- sources
class CpuLoad:
    name = "load"
    unit = "%"

    def __init__(self):
        self.prev = self._read()

    @staticmethod
    def _read():
        with open("/proc/stat") as f:
            parts = f.readline().split()
        vals = list(map(int, parts[1:]))
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        return idle, sum(vals)

    def read(self):
        idle, total = self._read()
        d_idle, d_total = idle - self.prev[0], total - self.prev[1]
        self.prev = (idle, total)
        if d_total <= 0:
            return 0.0
        return 100.0 * (1.0 - d_idle / d_total)


class CpuTemp:
    name = "temp"
    unit = "C"

    def __init__(self, sensor_name, sensor_label):
        self.path = None
        while self.path is None:
            self.path = self._find(sensor_name, sensor_label)
            if self.path is None:
                log(f"sensor {sensor_name}/{sensor_label} not found, retrying in 5s")
                time.sleep(5)
        log(f"sensor: {self.path}")

    @staticmethod
    def _find(name, label):
        for hw in glob.glob("/sys/class/hwmon/hwmon*"):
            try:
                if open(hw + "/name").read().strip() != name:
                    continue
            except OSError:
                continue
            for lab in glob.glob(hw + "/temp*_label"):
                if open(lab).read().strip() == label:
                    return lab.replace("_label", "_input")
            if not label:  # no label requested: take temp1
                cand = hw + "/temp1_input"
                if os.path.exists(cand):
                    return cand
        return None

    def read(self):
        with open(self.path) as f:
            return int(f.read().strip()) / 1000.0


def make_source(conf):
    if conf["source"] == "temp":
        return CpuTemp(conf["sensor_name"], conf["sensor_label"])
    return CpuLoad()


# --------------------------------------------------------------------------- colour
def hex2rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb2hex(c):
    return "%02X%02X%02X" % c


def color_for(v, gradient):
    if v <= gradient[0][0]:
        return hex2rgb(gradient[0][1])
    if v >= gradient[-1][0]:
        return hex2rgb(gradient[-1][1])
    for (v0, c0), (v1, c1) in zip(gradient, gradient[1:]):
        if v0 <= v <= v1:
            f = (v - v0) / (v1 - v0) if v1 > v0 else 1.0
            a, b = hex2rgb(c0), hex2rgb(c1)
            return tuple(int(round(a[i] + (b[i] - a[i]) * f)) for i in range(3))
    return hex2rgb(gradient[-1][1])


def quantize(c, q):
    if q <= 1:
        return c
    return tuple(min(255, int(round(x / q) * q)) for x in c)


def set_color(conf, hexcolor, dry_run=False):
    ok = True
    for dev in conf["devices"]:
        cmd = list(conf["openrgb"]) + ["--device", str(dev), "--mode", conf["mode"], "--color", hexcolor]
        if dry_run:
            log("DRY-RUN " + " ".join(cmd))
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except Exception as e:  # noqa: BLE001
            log(f"openrgb failed: {e}")
            ok = False
            continue
        out = r.stdout + r.stderr
        if r.returncode != 0 or "Connected to server" not in out:
            log(f"openrgb rc={r.returncode}: {out.strip()[-300:]}")
            ok = False
    return ok


# --------------------------------------------------------------------------- main
def show_gradient(conf):
    g = conf["gradient"]
    lo, hi = g[0][0], g[-1][0]
    step = max(1.0, (hi - lo) / 20.0)
    v = lo
    while v <= hi + 1e-9:
        print(f"{v:7.1f} -> #{rgb2hex(quantize(color_for(v, g), conf['quantize']))}")
        v += step


def main():
    ap = argparse.ArgumentParser(description="Drive RGB lighting from CPU load/temperature via OpenRGB.")
    ap.add_argument("--config", default=DEFAULT_CONF, help=f"JSON config file (default: {DEFAULT_CONF})")
    ap.add_argument("--dry-run", action="store_true", help="log what would be sent, do not call openrgb")
    ap.add_argument("--show-gradient", action="store_true", help="print the value -> colour table and exit")
    ap.add_argument("--set", metavar="VALUE", type=float, help="apply the colour for VALUE once and exit")
    args = ap.parse_args()

    conf = load_conf(args.config)
    if args.show_gradient:
        show_gradient(conf)
        return 0
    if args.set is not None:
        hexc = rgb2hex(quantize(color_for(args.set, conf["gradient"]), conf["quantize"]))
        log(f"{args.set} -> #{hexc}")
        return 0 if set_color(conf, hexc, args.dry_run) else 1

    state = {"run": True, "reload": False}
    signal.signal(signal.SIGTERM, lambda *_: state.update(run=False))
    signal.signal(signal.SIGINT, lambda *_: state.update(run=False))
    signal.signal(signal.SIGHUP, lambda *_: state.update(reload=True))

    src = make_source(conf)
    log(f"source: {conf['source']} ({src.name}); gradient: {conf['gradient']}")
    ema = None
    last_hex = None
    last_sent = 0.0
    fails = 0
    while state["run"]:
        if state["reload"]:
            state["reload"] = False
            new = load_conf(args.config)
            if new["source"] != conf["source"] or new.get("sensor_name") != conf.get("sensor_name") \
                    or new.get("sensor_label") != conf.get("sensor_label"):
                src = make_source(new)
                ema = None
            conf = new
            last_hex = None
            log(f"config reloaded: source {conf['source']}, gradient {conf['gradient']}")
        try:
            v = src.read()
        except OSError as e:
            log(f"error reading source: {e}")
            time.sleep(conf["poll_seconds"])
            continue
        a = conf["smoothing"]
        ema = v if ema is None else (a * v + (1 - a) * ema)
        hexc = rgb2hex(quantize(color_for(ema, conf["gradient"]), conf["quantize"]))
        now = time.monotonic()
        if hexc != last_hex and (now - last_sent) >= conf["min_update_seconds"]:
            if set_color(conf, hexc, args.dry_run):
                log(f"{src.name}={v:.1f}{src.unit} (smoothed {ema:.1f}{src.unit}) -> #{hexc}")
                last_hex = hexc
                fails = 0
            else:
                fails += 1
                time.sleep(min(30, 2 * fails))
            last_sent = time.monotonic()
        time.sleep(conf["poll_seconds"])
    log("exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())

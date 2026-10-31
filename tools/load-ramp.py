#!/usr/bin/env python3
"""Synthetic CPU load ramp for testing cpu-rgb.

Spawns one worker per CPU; their duty cycle rises linearly from 1% to 100% over
RAMP seconds, holds 100% for HOLD seconds, then exits.

    python3 tools/load-ramp.py [RAMP=90] [HOLD=15]
"""
import hashlib
import multiprocessing as mp
import os
import sys
import time

RAMP = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
HOLD = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
N = os.cpu_count() or 1


def load_pct(prev):
    with open("/proc/stat") as f:
        v = list(map(int, f.readline().split()[1:]))
    idle, total = v[3] + v[4], sum(v)
    if prev is None:
        return 0.0, (idle, total)
    di, dt = idle - prev[0], total - prev[1]
    return (100.0 * (1 - di / dt) if dt else 0.0), (idle, total)


def worker(duty, stop):
    period = 0.1
    buf = b"x" * 65536
    while not stop.value:
        d = duty.value
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < period * d:
            hashlib.sha256(buf).digest()
        time.sleep(max(0.0, period * (1 - d)))


if __name__ == "__main__":
    duty = mp.Value("d", 0.01)
    stop = mp.Value("i", 0)
    ps = [mp.Process(target=worker, args=(duty, stop)) for _ in range(N)]
    for p in ps:
        p.start()
    print(f"{N} workers | ramp {RAMP:.0f}s 1%->100% | hold {HOLD:.0f}s")
    print(" t(s)  target  measured")
    t0 = time.time()
    prev = None
    last = -9
    try:
        while True:
            el = time.time() - t0
            if el < RAMP:
                duty.value = max(0.01, el / RAMP)
            elif el < RAMP + HOLD:
                duty.value = 1.0
            else:
                break
            if el - last >= 3:
                pct, prev = load_pct(prev)
                print(f"{el:5.0f}  {duty.value * 100:5.0f}%  {pct:6.1f}%", flush=True)
                last = el
            time.sleep(0.5)
    finally:
        stop.value = 1
        for p in ps:
            p.join()
    print("done")

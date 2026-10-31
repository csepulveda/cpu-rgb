# cpu-rgb

Drive your PC's RGB lighting from **CPU load** (or CPU temperature) on Linux, through
[OpenRGB](https://openrgb.org).

Idle → white, light work → blue/cyan, medium → green/yellow, full load → orange/red.
The colour is interpolated continuously along a gradient you define, smoothed so it does
not flicker, and pushed to any device OpenRGB can control: motherboard ARGB headers (case
fans, CPU cooler), RAM, GPU, keyboards…

```
load  0%  ████ #FFFFFF  white
     10%  ████ #0000FF  blue
     25%  ████ #00FFFF  cyan
     40%  ████ #00FF00  green
     60%  ████ #FFFF00  yellow
     80%  ████ #FF8000  orange
    100%  ████ #FF0000  red
```

## Why

Vendor RGB software (Antec iUnity, Gigabyte RGB Fusion, …) is Windows-only. OpenRGB already
speaks to the hardware on Linux; `cpu-rgb` is the small daemon on top that turns a system
metric into a colour and keeps it updated. No compiled dependencies: Python 3 standard
library plus the `openrgb` binary.

## How it works

1. An **OpenRGB SDK server** (`openrgb --server`) runs as a system service and is the only
   process that talks to the hardware.
2. `cpu-rgb` samples a metric every `poll_seconds`:
   * `source = "cpu"`  → total CPU utilisation in %, from `/proc/stat`
   * `source = "temp"` → a hwmon temperature in °C (AMD `k10temp`/`Tctl`, Intel
     `coretemp`/`Package id 0`, …)
3. The value is smoothed with an exponential moving average and mapped to a colour by
   linear interpolation between the `gradient` anchor points.
4. When the (quantised) colour changes, `cpu-rgb` calls `openrgb --client … --mode static
   --color RRGGBB`. Because it connects to the local server, each update is instant and does
   not re-detect hardware.

Hardware "static" mode is used on purpose: on some controllers (e.g. Gigabyte IT5711 on
X870 boards) OpenRGB's per-LED *Direct* mode does not work, while the firmware static mode
does.

## Requirements

* Linux with systemd
* Python ≥ 3.8
* [OpenRGB](https://openrgb.org) ≥ 0.9 with your device detected (`openrgb --list-devices`)
* OpenRGB's udev rules installed (they ship with the package on most distros)

## Install

```sh
git clone https://github.com/csepulveda/cpu-rgb.git
cd cpu-rgb
sudo ./install.sh
```

The installer:

* copies `cpu-rgb.py` to `/usr/local/bin/cpu-rgb`
* creates `/etc/cpu-rgb.conf` from `cpu-rgb.conf.example` (kept if it already exists)
* installs and enables `openrgb-server.service` and `cpu-rgb.service`
* creates `/etc/openrgb` for the server and copies your `~/.config/OpenRGB/sizes.ors` and
  `OpenRGB.json` into it if present (see *Zone sizes* below)

Check it:

```sh
systemctl status openrgb-server cpu-rgb
journalctl -u cpu-rgb -f          # one line per colour change
```

Uninstall with `sudo ./uninstall.sh` (add `--purge` to also delete the config files).

## Configuration

`/etc/cpu-rgb.conf` is JSON. Apply changes with `sudo systemctl reload cpu-rgb`.

| Key | Default | Meaning |
|---|---|---|
| `source` | `"cpu"` | `"cpu"` = CPU load in %, `"temp"` = hwmon temperature in °C |
| `gradient` | see example | List of `[value, "RRGGBB"]` anchors. Colours are interpolated between anchors and clamped outside the range. |
| `poll_seconds` | `2.0` | Sampling interval |
| `smoothing` | `0.4` | EMA factor, 0–1. Higher reacts faster, lower is calmer. `1.0` disables smoothing. |
| `min_update_seconds` | `3.0` | Never send updates more often than this |
| `quantize` | `8` | Round each RGB channel to a multiple of this before comparing; avoids sending near-identical colours |
| `sensor_name` / `sensor_label` | `"k10temp"` / `"Tctl"` | hwmon chip name and temperature label, only for `source = "temp"`. Find yours with `sensors` or in `/sys/class/hwmon/hwmon*/name`. |
| `openrgb` | `["/usr/bin/openrgb","--client","127.0.0.1:6742","--nodetect"]` | Command prefix used to reach the OpenRGB server |
| `devices` | `[0]` | OpenRGB device indices to update (`openrgb --client 127.0.0.1:6742 --nodetect --list-devices`) |
| `mode` | `"static"` | OpenRGB mode name to use. Keep `static` unless you know your controller handles others. |

### Gradient examples

CPU load (default):

```json
"source": "cpu",
"gradient": [[0,"FFFFFF"],[10,"0000FF"],[25,"00FFFF"],[40,"00FF00"],[60,"FFFF00"],[80,"FF8000"],[100,"FF0000"]]
```

CPU temperature, tuned for an AMD Ryzen 9800X3D (idle ≈ 45 °C, all-core limit 95 °C):

```json
"source": "temp",
"gradient": [[48,"0000FF"],[55,"00FFFF"],[65,"00FF00"],[75,"FFFF00"],[85,"FF6000"],[92,"FF0000"]]
```

Two colours only, blue → red:

```json
"gradient": [[0,"0000FF"],[100,"FF0000"]]
```

Preview any gradient without touching hardware:

```sh
cpu-rgb --config /etc/cpu-rgb.conf --show-gradient
cpu-rgb --set 55 --dry-run     # colour for value 55, prints the openrgb command
cpu-rgb --set 55               # actually apply it once
```

## Testing with a synthetic load

`tools/load-ramp.py` ramps all cores from 1 % to 100 % over N seconds, holds, then exits:

```sh
python3 tools/load-ramp.py 90 15      # 90 s ramp, 15 s at 100 %
journalctl -u cpu-rgb -f              # in another terminal
```

## Zone sizes (ARGB headers)

OpenRGB reports addressable headers ("Digital LED 1/2/3", "D_LED", "JRAINBOW", …) with
**0 LEDs** until you tell it how many are connected. With zero LEDs the static colour still
applies on many boards, but if nothing lights up, set a size once:

```sh
# stop the server so the CLI can talk to the hardware directly
sudo systemctl stop cpu-rgb openrgb-server
openrgb --noautoconnect --device 0 --zone 0 --size 64 --mode static --color FF0000
openrgb --noautoconnect --device 0 --zone 1 --size 64 --mode static --color FF0000
# sizes are stored in ~/.config/OpenRGB/sizes.ors; copy it for the server
sudo cp ~/.config/OpenRGB/sizes.ors /etc/openrgb/
sudo systemctl start openrgb-server cpu-rgb
```

Or resize in the OpenRGB GUI and copy `sizes.ors` the same way.

## Troubleshooting

* **Everything turns off instead of changing colour** – the controller does not support
  the mode being used. Make sure `mode` is `static`, not `direct`.
* **`openrgb server has no devices`** in the journal – the server started but found nothing.
  Run `openrgb --noautoconnect --list-devices` as root; check udev rules and that your device
  is on the [OpenRGB supported list](https://openrgb.org/devices.html).
* **RAM / GPU not detected** – load `i2c-dev` (and `i2c-piix4` on AMD, `i2c-i801` on Intel).
  See [help.openrgb.org](https://help.openrgb.org/).
* **Using the OpenRGB GUI while the daemon runs** – the GUI connects to the local server
  automatically, so both can coexist. Changes you make by hand are overwritten at the next
  colour change.
* **Manual CLI changes** – always go through the server while it is running:
  `openrgb --client 127.0.0.1:6742 --nodetect --device 0 --mode static --color 00FF00`.
  Running the CLI with `--noautoconnect` at the same time opens the hidraw device twice and
  can confuse the controller.

## Tested on

* Gentoo Linux, kernel 6.18, OpenRGB 0.9 (git), systemd
* Gigabyte X870 GAMING WIFI6 (ITE IT5711 "RGB Fusion 2 USB"), Antec Flux Pro case fans and
  CPU cooler on the board's ARGB headers, AMD Ryzen 7 9800X3D

## License

MIT – see [LICENSE](LICENSE).

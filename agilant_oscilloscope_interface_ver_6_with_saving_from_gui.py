# -*- coding: utf-8 -*-
"""
InfiniiVision waveform export - full corrected script

Features:
- Primary CSV: single Time column + Channel A/B/C... with units row (s or us selectable)
- Optional exact per-channel interleaved CSV (Time A, Channel A, Time B, Channel B,...)
- Robust binary reads (BYTE/WORD) and careful scaling using waveform preamble
- CLI flags: --save-plots, --points, --outdir, --basename, --exact-save, --time-unit {s,us}, --arm-after

Usage examples:
  python infinii_collect_exact_points_full_corrected.py --save-plots --time-unit us
  python infinii_collect_exact_points_full_corrected.py --exact-save --time-unit s
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt

try:
    import pyvisa as visa
except Exception:
    import visa  # type: ignore

# ----------------- Defaults (edit if you like) -----------------
DEFAULT_SCOPE_IP = "169.254.254.254"
DEFAULT_POINTS = None  # if provided, will request this many points; otherwise use MAX available
GLOBAL_TOUT = 10000  # ms
BASE_FILE_NAME = "test"
BASE_DIRECTORY = r"D:\PhD data\oscilloscope_data"
# ---------------------------------------------------------------

os.makedirs(BASE_DIRECTORY, exist_ok=True)

CHANNEL_LABELS = {1: 'A', 2: 'B', 3: 'C', 4: 'D'}


def discover_and_open(scope_ip: str | None, global_tout_ms: int = GLOBAL_TOUT):
    rm = visa.ResourceManager()
    print("VISA backend:", getattr(rm, 'visalib', 'unknown'))
    try:
        resources = rm.list_resources()
    except Exception as e:
        resources = []
        print('Resource listing failed:', e)

    print("Discovered VISA resources:", resources)

    candidates = []
    if scope_ip:
        candidates += [
            f"TCPIP0::{scope_ip}::INSTR",
            f"TCPIP0::{scope_ip}::inst0::INSTR",
            f"TCPIP0::{scope_ip}::5025::SOCKET",
            f"TCPIP::{scope_ip}::INSTR",
            f"TCPIP::{scope_ip}::5025::SOCKET",
        ]
    for r in resources:
        if r not in candidates:
            candidates.append(r)

    print("Try order:")
    for c in candidates:
        print("  ", c)

    for addr in candidates:
        try:
            print("Trying:", addr)
            scope = rm.open_resource(addr)
            try:
                scope.timeout = global_tout_ms
            except Exception:
                scope.timeout = global_tout_ms / 1000.0
            try:
                idn = scope.query("*IDN?")
                print("IDN:", idn.strip())
            except Exception:
                print("Opened but *IDN? failed or timed out for", addr)
            return rm, scope, addr
        except Exception as e:
            print("Failed to open {} -> {}".format(addr, e))

    raise RuntimeError("Could not open any VISA resource. Check network/connection/Keysight IO libs.")


def set_scope_max_record(scope):
    try:
        scope.write(":ACQuire:POINts MAX")
    except Exception:
        pass
    try:
        scope.write(":WAVeform:POINts MAX")
        scope.write(":WAVeform:POINts:MODE RAW")
        print("Requested WAVeform POINts MAX + RAW")
    except Exception:
        pass


def get_channel_list(scope, max_ch: int = 4):
    chs = []
    ch_units = {}
    analog_preamble = {}

    for ch in range(1, max_ch + 1):
        try:
            on_off = int(scope.query(f":CHANnel{ch}:DISPlay?").strip())
        except Exception:
            on_off = 0
        if on_off == 1:
            try:
                ch_pts = int(scope.query(f":WAVeform:SOURce CHANnel{ch};POINts?").strip())
            except Exception:
                ch_pts = 0
            if ch_pts > 0:
                chs.append(ch)
                try:
                    pre = scope.query(f":WAVeform:SOURce CHANnel{ch};PREamble?").split(',')
                    analog_preamble[ch] = {
                        'YINCrement': float(pre[7]),
                        'YORigin': float(pre[8]),
                        'YREFerence': float(pre[9]),
                    }
                except Exception:
                    analog_preamble[ch] = None
                try:
                    ch_units[ch] = scope.query(f":CHANnel{ch}:UNITs?").strip()
                except Exception:
                    ch_units[ch] = 'V'

    if len(chs) == 0:
        raise RuntimeError("No active channels with data found")

    return chs, ch_units, analog_preamble


def fetch_channel_data(scope, ch: int):
    """Fetch exact time vector and raw integer samples for channel ch.
    Returns: (t: np.ndarray, raw: np.ndarray, x_increment: float)
    """
    scope.write(f":WAVeform:SOURce CHANnel{ch}")

    try:
        wavfmt = scope.query(":WAVeform:FORMat?").strip().upper()
    except Exception:
        wavfmt = "UNKNOWN"
    try:
        pts_reported = int(scope.query(":WAVeform:POINts?").strip())
    except Exception:
        pts_reported = None
    print(f"Channel {ch}: WAV:FORMAT? -> {wavfmt}, WAVeform:POINts? -> {pts_reported}")

    pre_raw = scope.query(":WAVeform:PREamble?").strip()
    pre = pre_raw.split(',')
    try:
        X_INCREMENT = float(pre[4])
        X_ORIGIN = float(pre[5])
        X_REFERENCE = float(pre[6])
    except Exception as e:
        raise RuntimeError(f"Could not parse time preamble for channel {ch}: {e}")

    raw = np.array([], dtype=float)

    if "BYTE" in wavfmt:
        try:
            raw_vals = scope.query_binary_values(f":WAVeform:SOURce CHANnel{ch};DATA?", datatype='B', is_big_endian=False)
            raw = np.array(raw_vals, dtype=float)
            print(f"Channel {ch}: read {raw.size} BYTE samples")
        except Exception as e:
            raise RuntimeError(f"BYTE binary read failed for channel {ch}: {e}")
    else:
        for be in (False, True):
            try:
                raw_try = scope.query_binary_values(f":WAVeform:SOURce CHANnel{ch};DATA?", datatype='h', is_big_endian=be)
                raw_try = np.array(raw_try, dtype=float)
            except Exception as e:
                print(f"Channel {ch}: 16-bit read failed (is_big_endian={be}): {e}")
                raw_try = np.array([], dtype=float)

            if raw_try.size == 0:
                continue
            if np.max(np.abs(raw_try)) < 1e6:
                raw = raw_try
                print(f"Channel {ch}: using 16-bit read (is_big_endian={be}), samples={raw.size}, absmax={np.max(np.abs(raw)):.0f}")
                break
            else:
                print(f"Channel {ch}: 16-bit read looks suspicious (absmax={np.max(np.abs(raw_try)):.0f})")

        if raw.size == 0:
            raise RuntimeError(f"Failed to read waveform data for channel {ch}")

    if pts_reported is not None and raw.size != pts_reported:
        print(f"Warning: channel {ch} reported {pts_reported} points but actual read {raw.size}. Using actual sample count.")
    pts = raw.size

    idx = np.arange(pts)
    t = X_ORIGIN + (idx - X_REFERENCE) * X_INCREMENT

    return t, raw, X_INCREMENT


def scale_channel_data(data: np.ndarray, ch: int, analog_preamble: dict):
    if analog_preamble and ch in analog_preamble and analog_preamble[ch] is not None:
        yinc = analog_preamble[ch]['YINCrement']
        yorig = analog_preamble[ch]['YORigin']
        yref = analog_preamble[ch]['YREFerence']
        return ((data - yref) * yinc) + yorig
    else:
        return data


def interpolate_to_common(common_t, t_ch, y_ch):
    if t_ch.size == 0 or y_ch.size == 0:
        return np.full(common_t.shape, np.nan)
    interp = np.interp(common_t, t_ch, y_ch)
    outside = (common_t < t_ch[0]) | (common_t > t_ch[-1])
    if outside.any():
        interp[outside] = np.nan
    return interp


def build_common_time_axis(t_list, xincs, max_points_cap=10_000_000):
    t_min = min([t[0] for t in t_list])
    t_max = max([t[-1] for t in t_list])
    min_inc = min(xincs)
    npoints = int(np.floor((t_max - t_min) / min_inc)) + 1
    if npoints > max_points_cap:
        raise RuntimeError(f"Common axis would have {npoints} points (exceeds cap). Reduce requested resolution.")
    common = t_min + np.arange(npoints) * min_inc
    if common[-1] < t_max:
        common = np.append(common, t_max)
    return common


def write_separate_csv(outpath, t_list, channel_arrays, ch_list, ch_units):
    header1 = []
    header2 = []
    for ch in ch_list:
        label = CHANNEL_LABELS.get(ch, str(ch))
        header1.extend([f"Time {label}", f"Channel {label}"])
        header2.extend(["(s)", f"({ch_units.get(ch, 'V')})"])

    nrows = max([len(t) for t in t_list])

    with open(outpath, 'w', newline='') as fh:
        fh.write(','.join(header1) + '\n')
        fh.write(','.join(header2) + '\n')
        fh.write('\n')
        for i in range(nrows):
            row = []
            for idx in range(len(ch_list)):
                t_arr = t_list[idx]
                y_arr = channel_arrays[idx]
                if i < len(t_arr):
                    row.append(f"{t_arr[i]:.12g}")
                    row.append(f"{y_arr[i]:.12g}")
                else:
                    row.append("")
                    row.append("")
            fh.write(','.join(row) + '\n')
    print('Wrote exact per-channel CSV:', outpath)


def write_common_csv(outpath, common_t, channel_arrays, ch_list, ch_units, time_unit='us'):
    time_factor = 1e6 if time_unit == 'us' else 1.0
    unit_label = '(us)' if time_unit == 'us' else '(s)'

    header = ['Time'] + [f"Channel {CHANNEL_LABELS.get(ch, ch)}" for ch in ch_list]
    units = [unit_label] + [f"({ch_units.get(ch,'V')})" for ch in ch_list]

    nrows = len(common_t)
    with open(outpath, 'w', newline='') as fh:
        fh.write(','.join(header) + '\n')
        fh.write(','.join(units) + '\n')
        fh.write('\n')
        for i in range(nrows):
            row = [f"{common_t[i]*time_factor:.9g}"]
            for idx in range(len(ch_list)):
                val = channel_arrays[idx][i]
                if np.isnan(val):
                    row.append('')
                else:
                    row.append(f"{val:.9g}")
            fh.write(','.join(row) + '\n')
    print('Wrote common-axis CSV:', outpath)


def plot_exact_channels(t_list, y_list, ch_list, ch_units, save_plots: bool, outdir: str, base_name: str):
    plt.figure(figsize=(10, 6))
    for idx, ch in enumerate(ch_list):
        t_arr = t_list[idx]
        y_arr = y_list[idx]
        y_masked = np.ma.masked_invalid(y_arr)
        plt.plot(t_arr, y_masked, label=f"Ch{CHANNEL_LABELS.get(ch, ch)} ({ch_units.get(ch,'V')})")
    plt.xlabel('Time (s)')
    plt.ylabel('Voltage')
    plt.title('Channels (exact points)')
    plt.legend()
    plt.grid(True)
    if save_plots:
        fname = os.path.join(outdir, f"{base_name}_combined.png")
        plt.savefig(fname)
        print('Saved plot to', fname)
        plt.close()
    else:
        plt.show()


def arm_scope_for_next(scope):
    try:
        scope.write(":SINGle")
        print("Scope armed for next single acquisition (:SINGle sent)")
    except Exception as e:
        print("Failed to arm scope:", e)


def parse_args():
    p = argparse.ArgumentParser(description='Collect exact waveform points, scale and save per-channel CSV')
    p.add_argument('--scope-ip', default=DEFAULT_SCOPE_IP)
    p.add_argument('--save-plots', action='store_true')
    p.add_argument('--points', type=int, default=DEFAULT_POINTS, help='Request this many waveform points (overrides MAX)')
    p.add_argument('--outdir', default=BASE_DIRECTORY)
    p.add_argument('--basename', default=BASE_FILE_NAME)
    p.add_argument('--max-rows', type=int, default=10, help='How many rows of combined data to print per channel')
    p.add_argument('--arm-after', action='store_true', help='Arm the scope (SINGLE) after saving')
    p.add_argument('--exact-save', action='store_true', help='Also save exact per-channel CSV (interleaved Time/Channel columns')
    p.add_argument('--time-unit', choices=['s', 'us'], default='us', help='Time unit to write in the common CSV')
    return p.parse_args()


def main():
    args = parse_args()
    outdir = args.outdir
    base_name = args.basename
    os.makedirs(outdir, exist_ok=True)

    print('Starting collection:', datetime.now().isoformat())

    rm, scope, used = discover_and_open(args.scope_ip, GLOBAL_TOUT)

    try:
        set_scope_max_record(scope)

        if args.points:
            try:
                scope.write(f":WAVeform:POINts {int(args.points)}")
                print('Requested points set to', args.points)
            except Exception as e:
                print('Could not set requested points:', e)

        ch_list, ch_units, analog_preamble = get_channel_list(scope, max_ch=4)
        print('Active channels with data:', ch_list)

        t_list = []
        raw_list = []
        xincs = []
        for ch in ch_list:
            t_ch, data_ch, xinc = fetch_channel_data(scope, ch)
            scaled = scale_channel_data(data_ch, ch, analog_preamble)
            t_list.append(t_ch)
            raw_list.append(scaled)
            xincs.append(xinc)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # build common axis and write the main CSV in single-Time format (matching your required header)
        try:
            common_t = build_common_time_axis(t_list, xincs)
            interp_arrays = [interpolate_to_common(common_t, t_list[i], raw_list[i]) for i in range(len(ch_list))]
            outpath_common = os.path.join(outdir, f"{base_name}_{timestamp}.csv")
            write_common_csv(outpath_common, common_t, interp_arrays, ch_list, ch_units, time_unit=args.time_unit)
            print('Saved common-axis CSV to', outpath_common)
        except Exception as e:
            print('Failed to create common-axis CSV:', e)

        # optionally also save exact per-channel interleaved CSV if requested
        if args.exact_save:
            try:
                outpath_exact = os.path.join(outdir, f"{base_name}_{timestamp}_exact.csv")
                write_separate_csv(outpath_exact, t_list, raw_list, ch_list, ch_units)
                print('Saved exact-sample CSV to', outpath_exact)
            except Exception as e:
                print('Failed to save exact-sample CSV:', e)

        # print first rows per channel for quick inspection
        n_print = min(args.max_rows, max([len(t) for t in t_list]))
        for idx, ch in enumerate(ch_list):
            label = CHANNEL_LABELS.get(ch, str(ch))
            print(f"\nFirst {n_print} samples for Channel {label} (Ch{ch}):")
            print('Time(s), Voltage')
            for i in range(min(n_print, len(t_list[idx]))):
                print(f"{t_list[idx][i]:.9g}, {raw_list[idx][i]:.9g}")

        # plot (supply list of (t_arr, y_arr) to plotting function)
        try:
            plot_exact_channels(t_list, raw_list, ch_list, ch_units, args.save_plots, outdir, base_name)
        except Exception as e:
            print('Plotting failed:', e)

        if args.arm_after:
            arm_scope_for_next(scope)

    finally:
        try:
            scope.clear()
            scope.close()
        except Exception:
            pass
        try:
            rm.close()
        except Exception:
            pass

    print('Done at', datetime.now().isoformat())



if __name__ == '__main__':
    main()

def collect_waveform_and_save_once(
    outdir,
    first4,            # string: the 4-character prefix
    wavelength,        # string, e.g. "1064nm"
    pressure_str,      # string, e.g. "100e+1mbar" or "1e-1mbar" (you enter the exact text you want in filename)
    energy_mj,         # integer or string, e.g. 50  -> will be formatted as 050mj
    timescale_us,      # integer or string, e.g. 1  -> will be formatted as 001us
    posnum,            # integer position number to include in filename
    pulsenum,          # integer pulse number to include in filename
    scope_ip=DEFAULT_SCOPE_IP,
    points=None,
    save_plots=False,
    arm_after=False,
    base_name=None
):
    """
    Collect once from scope and save combined CSV with a filename constructed like:
      {first4}_{wavelength}_{pressure_str}_{energy_str}_{timescale_str}_pos{posnum}_p{pulsenum}.csv

    Returns the full path to the saved file (string) on success, or raises on error.
    """
    # normalize / format fields
    energy_int = int(energy_mj) if energy_mj is not None and str(energy_mj).strip() != '' else 0
    timescale_int = int(timescale_us) if timescale_us is not None and str(timescale_us).strip() != '' else 0

    energy_str = f"{energy_int:03d}mj"        # 050mj
    timescale_str = f"{timescale_int:03d}us"  # 001us

    # build filename base
    if first4 is None:
        first4 = ""
    fname_base = f"{first4}_{wavelength}nm_{pressure_str}mbar_{energy_str}_{timescale_str}_pos{posnum}_p{pulsenum}"
    if base_name:
        # optionally preserve some base_name prefix
        fname_base = f"{fname_base}"

    # ensure outdir exists
    os.makedirs(outdir, exist_ok=True)

    # Discover & open scope
    rm, scope, used_addr = discover_and_open(scope_ip, GLOBAL_TOUT)

    # try to set maximum records and requested points
    try:
        set_scope_max_record(scope)
        if points:
            try:
                scope.write(f":WAVeform:POINts {int(points)}")
            except Exception:
                pass

        # obtain channel list & data (re-using existing functions)
        ch_list, ch_units, analog_preamble = get_channel_list(scope, max_ch=4)

        t_list = []
        raw_list = []
        xincs = []
        for ch in ch_list:
            t_ch, data_ch, xinc = fetch_channel_data(scope, ch)
            scaled = scale_channel_data(data_ch, ch, analog_preamble)
            t_list.append(t_ch)
            raw_list.append(scaled)
            xincs.append(xinc)

        common_t = build_common_time_axis(t_list, xincs)
        channel_arrays = [interpolate_to_common(common_t, t_list[idx], raw_list[idx]) for idx in range(len(ch_list))]

        # save CSV
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        outname = f"{fname_base}.csv"
        outpath = os.path.join(outdir, outname)

        write_common_csv(outpath, common_t, channel_arrays, ch_list, ch_units,time_unit='us')

        # optional plot saving
        #if save_plots:
            #plot_all(common_t, channel_arrays, ch_list, ch_units, True, outdir, fname_base)

        if arm_after:
            arm_scope_for_next(scope)

        return outpath

    finally:
        # cleanup
        try:
            scope.clear()
            scope.close()
        except Exception:
            pass
        try:
            rm.close()
        except Exception:
            pass

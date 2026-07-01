 # -*- coding: utf-8 -*-
"""
Created on Tue Oct 14 10:05:52 2025

@author: Renjith Kumar R
"""

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
  GENERAL PUMP-PROBE PLOTTER  —  nav CSV files
═══════════════════════════════════════════════════════════════════════════════
  Fix any combination of parameters; vary the rest.
  Supported parameters:
    prefix      → material + thickness  (e.g. 'a4', 's4', 's2', 'a2', 'ca')
    orientation → probe geometry        ('fa'=FA-FP, 'fp'=FA-RP, 'ba'=BA-RP, 'bp'=BA-FP)
    pressure    → gas pressure token    (e.g. '100e+0mbar')
    energy      → pulse energy token    (e.g. '060mj')
    pulse_width → pulse duration token  (e.g. '001us')
    pulse       → shot number           (integer, e.g. 1)

  PLOT_MODE:  'R' | 'T' | 'R|T' | 'overlay' | 'sum' | 'absorption' | 'all'
  LAYOUT:     'auto' (single row)  |  'grid' (2xN, rows=R/T, cols=GRID_PARAM)

  FIXED can be a single dict  → one figure
         or a LIST of dicts   → one separate figure per entry (no overplotting)

  File naming convention:
    {prefix}_{orient}_{wavelength}_{pressure}_{energy}_{pulse_width}_posv_p{N}_nav.csv
═══════════════════════════════════════════════════════════════════════════════
"""
"""
nav_and_plots_all_values_fixed.py

Preserves original normalization logic:
 - For each (base_prefix, pos_token) group: use earliest pulse (p_min) to compute min_trans_val & max_refl_val
   (average of first 8% of samples), use last pulse (p_max) to compute min_refl_val & max_trans_val
   (average of last 20% of samples).
 - Normalize each pulse file for that position using those 4 baseline numbers.
 - For averaging across positions for a given (pressure, fluence, pulse), apply similarity test (20% default).
 - Save _nav.csv files named: <base_prefix>posv_p{pulse}_nav.csv (exact pattern).
 - Produce 2x4 PNGs (pressure-scan and fluence-scan) at 500 dpi.
"""

import os
import glob
import re
import csv
import math
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy import signal
import matplotlib as mpl
import matplotlib.pyplot as plt
import scienceplots
from itertools import combinations
# --------------- USER PARAMETERS (edit) ----------------
PATH = r'D:\renjith_phD\Renjith_laser_data\Data collected directly\Silver_200nm_film'
FILE_PREFIXES = ['s2_fp']    # choose which file prefixes to process
plt.style.use(['science'])
# smoothing (keep these)
sampl = 3   # savgol window must be odd >=3 to be applied; set 1 to disable smoothing
poly  = 1    # polynomial order
sampl1 = 100   # savgol window must be odd >=3 to be applied; set 1 to disable smoothing
poly1  = 1    # polynomial order
# averaging / omission controls
SIMILARITY_THRESHOLD_PERCENT = 20.0
MIN_POSITIONS_TO_AVERAGE = 2
METRIC_CENTER_FRAC = 0.5   # central window fraction for similarity metric

# plotting controls
PULSES_TO_SHOW = [1,2,3,4,5,6]   # columns; adjust to include upto 9 if needed
FIG_DPI = 600
FIG_FIGSIZE = (16,8)
ERROR_SAMPLE_FRACTION = 0.08

# which plots to create
MAKE_PRESSURE_SCAN_PNG = True
MAKE_FLUENCE_SCAN_PNG = True

# produce for all available values if True; otherwise use lists below
PROCESS_ALL_PRESSURES = True
PROCESS_ALL_FLUENCES = True

# If PROCESS_ALL_* False, set these lists (pressure strings as printed by the script, and J/cm^2 floats)
PRESSURE_LIST_TO_PLOT = [0.5, 20.0, 100.0, 250.0, 500.0, 1000.0]            # e.g. ['500e+0mbar','250e+0mbar']
FLUENCE_LIST_TO_PLOT_JPCM2 =[15.3, 20.4]     # e.g. [5.093, 7.639]
# ------------------------------------------------------

mpl.rcParams['text.usetex'] = False
mpl.rcParams['font.family'] = 'sans-serif'

os.chdir(PATH)

# find csvs with required prefixes
all_csvs = sorted([f for f in glob.glob('*.csv') if any(f.startswith(pref) for pref in FILE_PREFIXES)])
if not all_csvs:
    raise FileNotFoundError(f"No CSV files with prefixes {FILE_PREFIXES} found in {PATH}")

# regex patterns
re_pressure = re.compile(r'(?P<num>[-+]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)mbar', re.IGNORECASE)
re_fluence  = re.compile(r'(?P<num>\d+(?:\.\d+)?)mj', re.IGNORECASE)
re_pulse    = re.compile(r'_p(?P<p>\d+)', re.IGNORECASE)
re_pos_token = re.compile(r'(_posv?_?\d+)', re.IGNORECASE)  # captures _pos1 or _posv1 etc.


import numpy as np

def float_match(a, b, tol=5e-4):
    try:
        return np.isclose(float(a), float(b), atol=tol, rtol=0)
    except Exception:
        return False

def get_subset_by_pressure(navdf, p_token):
    """Match either pressure_str (exact string) or numeric pressure_val (tolerant)."""
    # If user passed a string token and navdf has non-null pressure_str values, match by string
    if isinstance(p_token, str) and navdf['pressure_str'].notnull().any():
        return navdf[navdf['pressure_str'] == p_token]
    # Otherwise try numeric match
    try:
        pnum = float(p_token)
        mask = navdf['pressure_val'].apply(lambda v: float_match(v, pnum))
        return navdf[mask]
    except Exception:
        return navdf.iloc[0:0]  # empty

def mj_to_jpcm2(mj):
    if mj is None: return None
    E_J = float(mj) * 1e-3
    area = math.pi * (0.5 * 1e-1) ** 2
    return round(2 * E_J / area, 1)

def parse_filename(fname):
    pstr = None; pval = None; fmj = None; pulse=None; pos_token=None
    m = re_pressure.search(fname)
    if m:
        pstr = m.group(0)
        try: pval = float(m.group('num'))
        except: pval = None
    m = re_fluence.search(fname)
    if m:
        try: fmj = float(m.group('num'))
        except: fmj = None
    m = re_pulse.search(fname)
    if m:
        try: pulse = int(m.group('p'))
        except: pulse = None
    m = re_pos_token.search(fname)
    if m: pos_token = m.group(1)
    return {'fname': fname, 'pressure_str': pstr, 'pressure_val': pval, 'fluence_mj': fmj,
            'fluence_jpcm2': mj_to_jpcm2(fmj) if fmj is not None else None,
            'pulse': pulse, 'pos_token': pos_token}

meta = [parse_filename(f) for f in all_csvs]
meta_df = pd.DataFrame(meta)

available_pressure_strs = sorted({s for s in meta_df['pressure_str'].unique() if s is not None})
available_pressure_vals = sorted({v for v in meta_df['pressure_val'].unique() if v is not None})
available_fluences_mj = sorted({v for v in meta_df['fluence_mj'].unique() if v is not None})
available_fluences_jpcm2 = sorted({mj_to_jpcm2(m) for m in available_fluences_mj if m is not None})

print("\nFound CSV files:", len(all_csvs))
print("Available pressure strings (exact substrings found in filenames):", available_pressure_strs)
print("Available pressure numeric values (float):", available_pressure_vals)
print("Available fluences (mJ):", available_fluences_mj)
print("Available fluences (approx J/cm^2):", available_fluences_jpcm2)
print("----\nIf you want specific plots, set PRESSURE_LIST_TO_PLOT to exact pressure strings above\nand FLUENCE_LIST_TO_PLOT_JPCM2 to values above (J/cm^2). Otherwise set PROCESS_ALL_* = True.")

# expand lists if user requested all
if PROCESS_ALL_PRESSURES:
    PRESSURE_LIST_TO_PLOT = available_pressure_vals.copy()
else:
    if not PRESSURE_LIST_TO_PLOT and available_pressure_strs:
        PRESSURE_LIST_TO_PLOT = [available_pressure_strs[0]]
if PROCESS_ALL_FLUENCES:
    FLUENCE_LIST_TO_PLOT_JPCM2 = available_fluences_jpcm2.copy()
else:
    if not FLUENCE_LIST_TO_PLOT_JPCM2 and available_fluences_jpcm2:
        FLUENCE_LIST_TO_PLOT_JPCM2 = [available_fluences_jpcm2[0]]

print("\nPlots to produce:")
print("  Pressure-scan (single fluence) for fluences (J/cm^2):", FLUENCE_LIST_TO_PLOT_JPCM2)
print("  Fluence-scan (single pressure) for pressures (strings):", PRESSURE_LIST_TO_PLOT)

# ---------------- Build base_prefix -> pos_token -> list(files) mapping --------------
# base_prefix = filename up to BEFORE pos token (so base_prefix + pos_token + _p{N}.csv describes a set)
groups_by_base = defaultdict(lambda: defaultdict(list))
meta_by_name = {m['fname']: m for m in meta}

for info in meta:
    fname = info['fname']
    mpos = re_pos_token.search(fname)
    if not mpos:
        continue
    base_prefix = fname[:mpos.start()]     # keep up to char before _pos token
    pos_token = mpos.group(1)
    groups_by_base[base_prefix][pos_token].append(fname)

# trace reader with smoothing preserved
def read_trace(fname):
    with open(fname, 'r') as f:
        raw = list(csv.reader(f))
    if len(raw) < 4:
        raise ValueError(f"{fname} too short")
    exampledata = np.array(raw[3:], dtype=np.float64)
    try:
        df_all = pd.read_csv(fname)
        time_unit = df_all.Time.iloc[0]
        ca_unit = df_all['Channel A'].iloc[0]
        cb_unit = df_all['Channel B'].iloc[0]
        cc_unit = df_all['Channel C'].iloc[0]
    except Exception:
        time_unit='(us)'; ca_unit='(V)'; cb_unit='(V)'; cc_unit='(V)'
    if str(time_unit).strip() == '(us)':
        x = exampledata[:,0] * 1e-6
    elif str(time_unit).strip() == '(ns)':
        x = exampledata[:,0] * 1e-9
    elif str(time_unit).strip() == '(ms)':
        x = exampledata[:,0] * 1e-3
    else:
        x = exampledata[:,0] * 1e-6
    def conv(col_idx, unit):
        u = str(unit).strip().lower()
        arr = exampledata[:, col_idx]
        if u in ('(mv)', '(mv)'.lower()):
            return arr * 1e-3
        return arr
    y_refl = conv(1, ca_unit)
    y_trans = conv(2, cb_unit)
    y_laser = conv(3, cc_unit)
    yerr_refl = exampledata[:,4] if exampledata.shape[1] > 4 else np.zeros_like(x)
    yerr_trans = exampledata[:,5] if exampledata.shape[1] > 5 else np.zeros_like(x)
    # smoothing (preserve user's sampl/poly)
    if sampl is not None and poly is not None and sampl >=3 and sampl % 2 == 1 and sampl <= len(y_refl):
        try:
            y_refl = signal.savgol_filter(y_refl, sampl, poly)
            y_trans = signal.savgol_filter(y_trans, sampl, poly)
        except Exception:
            pass
    return x, y_refl, y_trans, y_laser, yerr_refl, yerr_trans

def baseline_from_first_and_last(pmin_fname, pmax_fname, data_length, early_frac=0.08, late_frac=0.20):
    """Compute the 4 baseline numbers from the user's original logic:
       - from first pulse file (pmin): min_trans_val (mean first early_frac of trans), max_refl_val (mean first early_frac of refl)
       - from last  pulse file (pmax): min_refl_val (mean last late_frac of refl), max_trans_val (mean last late_frac of trans)
       All arrays are negated (y * -1) before computing, to match original code.
    """
    x1, y_refl1, y_trans1, _, _, _ = read_trace(pmin_fname)
    refl1 = y_refl1 * -1.0
    trans1 = y_trans1 * -1.0
    n_early = max(1, int(round(early_frac * data_length)))
    min_trans_val = float(np.mean(trans1[0:n_early]))
    max_refl_val  = float(np.mean(refl1[0:n_early]))

    x2, y_refl2, y_trans2, _, _, _ = read_trace(pmax_fname)
    refl2 = y_refl2 * -1.0
    trans2 = y_trans2 * -1.0
    n_late = max(1, int(round(late_frac * data_length)))
    min_refl_val = float(np.mean(refl2[-n_late:]))
    max_trans_val = float(np.mean(trans2[-n_late:]))

    return min_trans_val, max_refl_val, min_refl_val, max_trans_val

def custom_normalize(value, mn, mx):
    if mx == mn:
        return np.zeros_like(value)
    return (value - mn) / (mx - mn)

# prepare storage for normalized signals by (base_prefix, fluence_jpcm2, pressure_str, pulse, pos_token)
# We'll also store the x_common we use (from first file encountered for that pos)
norm_store = defaultdict(lambda: dict())

created_nav = []
skipped_nav = []
omitted_report = []

# STEP A: For each base_prefix and each position token, compute baselines (from first & last pulses)
# and normalize each pulse file for that position.
for base_prefix, pos_dict in sorted(groups_by_base.items()):
    for pos_token, filelist in sorted(pos_dict.items()):
        # gather files that are _pN.csv
        # extract pulse numbers
        entries = []
        for f in sorted(filelist):
            m = re_pulse.search(f)
            if m:
                pnum = int(m.group('p'))
                entries.append({'fname': f, 'pulse': pnum})
        if not entries:
            continue
        entries = sorted(entries, key=lambda z: z['pulse'])
        p_min = entries[0]['pulse']
        p_max = entries[-1]['pulse']
        fname_min = entries[0]['fname']
        fname_max = entries[-1]['fname']
        # data_length as in your code: number of rows in CSV minus 1
        df_sample = pd.read_csv(entries[0]['fname'])
        data_length = max(1, len(df_sample) - 1)
        # compute baseline numbers (first and last pulses for this position)
        try:
            min_trans_val, max_refl_val, min_refl_val, max_trans_val = baseline_from_first_and_last(fname_min, fname_max, data_length)
        except Exception as e:
            print("Baseline error for", base_prefix, pos_token, ":", e)
            continue
        # For each pulse file for this pos, read, negate, (interpolate to x_common if needed) normalize using these baselines
        # x_common choose from first file for this pos (entries[0])
        x_common, _, _, _, _, _ = read_trace(entries[0]['fname'])
        n_common = len(x_common)
        for ent in entries:
            fname = ent['fname']; pulse_no = ent['pulse']
            try:
                x, y_refl, y_trans, y_laser, yerr_refl, yerr_trans = read_trace(fname)
            except Exception as e:
                print("Failed read", fname, e); continue
            refl_raw = y_refl * -1.0
            trans_raw = y_trans * -1.0
            # if lengths differ, interpolate to x_common
            if len(x) != n_common:
                refl_arr = np.interp(x_common, x, refl_raw)
                trans_arr = np.interp(x_common, x, trans_raw)
                yerr_refl_interp = np.interp(x_common, x, yerr_refl) if len(yerr_refl)==len(x) else np.zeros_like(x_common)
                yerr_trans_interp = np.interp(x_common, x, yerr_trans) if len(yerr_trans)==len(x) else np.zeros_like(x_common)
            else:
                refl_arr = refl_raw.copy(); trans_arr = trans_raw.copy()
                yerr_refl_interp = yerr_refl.copy(); yerr_trans_interp = yerr_trans.copy()
            # normalize exactly as your original script expects:
            refl_norm = custom_normalize(refl_arr, min_refl_val, max_refl_val) * 100.0
            trans_norm = custom_normalize(trans_arr, min_trans_val, max_trans_val) * 100.0
            laser_norm=y_laser
            # store into norm_store keyed by (base_prefix, pulse_no) grouped across positions
            key = (base_prefix, pulse_no)
            if 'x_common' not in norm_store[key]:
                norm_store[key]['x_common'] = x_common
                norm_store[key]['pressure_str'] = parse_filename(fname)['pressure_str']
                norm_store[key]['fluence_jpcm2'] = parse_filename(fname)['fluence_jpcm2']
            if 'positions' not in norm_store[key]:
                norm_store[key]['positions'] = []
            norm_store[key]['positions'].append({'pos_token': pos_token, 'fname': fname,
                                                'refl': refl_norm, 'trans': trans_norm, 'laser':y_laser,
                                                'yerr_refl': yerr_refl_interp, 'yerr_trans': yerr_trans_interp})

# STEP B: For each (base_prefix, pulse), average across positions (with similarity test)
def _compute_metrics_for_field(x_common, pos_list, field, center_frac):
    n = len(x_common)
    c0 = max(0, int(round(n * (0.5 - center_frac/2))))
    c1 = min(n, int(round(n * (0.5 + center_frac/2))))
    metrics = []
    for idx, pentry in enumerate(pos_list):
        if field not in pentry:
            metrics.append({'idx': idx, 'metric': np.nan})
            continue
        metric_val = float(np.mean(pentry[field][c0:c1]))
        metrics.append({'idx': idx, 'pos_token': pentry.get('pos_token'),
                        'fname': pentry.get('fname'), 'metric': metric_val})
    return metrics, c0, c1

# Choose strictness:
# 'either' = omit a position if EITHER trans OR refl deviates more than the threshold.
# 'both'   = omit only if BOTH trans AND refl deviate more than the threshold.
#OUTLIER_STRICTNESS = 'either'  # change to 'both' if you want less aggressive omission
# --- start corrected for-loop (paste in place of your old loop) ---


# parameters (uses your SIMILARITY_THRESHOLD_PERCENT if present)
STD_VARIATION_THRESHOLD_PERCENT = float(SIMILARITY_THRESHOLD_PERCENT) if 'SIMILARITY_THRESHOLD_PERCENT' in globals() else 20.0
COMBINATORIAL_LIMIT = 12     # exact subset search only for up to this many files
EPS = 1e-12                  # small number to avoid div-by-zero
selection_map = {}
for key, content in norm_store.items():
    base_prefix, pulse_no = key
    x_common = content['x_common']
    pos_list = content['positions']
    if len(pos_list) == 0:
        continue
    omit_info = []
    # compute metrics for transmission and reflection (existing function)
    trans_metrics, c0, c1 = _compute_metrics_for_field(x_common, pos_list, 'trans', METRIC_CENTER_FRAC)
    refl_metrics, _, _    = _compute_metrics_for_field(x_common, pos_list, 'refl', METRIC_CENTER_FRAC)

    def _metric_array(metrics):
        arr = np.array([m['metric'] if (m['metric'] is not None and not np.isnan(m['metric'])) else np.nan
                        for m in metrics], dtype=float)
        return arr

    trans_vals = _metric_array(trans_metrics)
    refl_vals  = _metric_array(refl_metrics)
# ------------------ Replace old selection with this block ------------------
# assumes: pos_list, base_prefix, pulse_no, MIN_POSITIONS_TO_AVERAGE,
#          SIMILARITY_THRESHOLD_PERCENT, omitted_report exist in scope.
    # ---------- Correct selection: std ACROSS positions (per-sample) ----------
# ---------- Keep-all-unless-needed selection (20% cutoff rule) ----------
# Requires: pos_list, x_common, MIN_POSITIONS_TO_AVERAGE, SIMILARITY_THRESHOLD_PERCENT, omitted_report
 # ------------------- Replace old keep/omit logic with this -------------------
    from itertools import combinations
    
    EPS = 1e-12
    EXHAUSTIVE_LIMIT = 14
    ROI_FRAC = 0.05
    MIN_KEEP = MIN_POSITIONS_TO_AVERAGE
    
    # build full mats for this pulse
    all_refl = np.vstack([p['refl'] for p in pos_list]).T
    all_trans = np.vstack([p['trans'] for p in pos_list]).T
    n_samples, npos = all_refl.shape
    if npos == 0:
        continue
    
    # baseline subtract (adjust pre_slice if you have a different baseline window)
    pre_slice = slice(0, max(1, int(0.05 * n_samples)))
    all_refl = all_refl - np.nanmean(all_refl[pre_slice, :], axis=0)
    all_trans = all_trans - np.nanmean(all_trans[pre_slice, :], axis=0)
    
    # ROI mask (pulse window) to avoid baseline artifacts
    mean_all = 0.5 * (np.nanmean(all_refl, axis=1) + np.nanmean(all_trans, axis=1))
    peak = np.nanmax(np.abs(mean_all)) + EPS
    roi_mask = np.abs(mean_all) > (ROI_FRAC * peak)
    if not np.any(roi_mask):
        roi_mask = np.ones(n_samples, dtype=bool)
    
    def channel_combined_relstd(mat_channel, idxs):
        """Time-averaged relative std% across positions (compute std across positions at each sample)."""
        if len(idxs) == 0:
            return float('inf')
        sel = mat_channel[roi_mask][:, idxs]  # shape (n_roi, n_kept)
        if sel.shape[1] == 1:
            return 0.0
        mean_t = np.nanmean(sel, axis=1)
        std_t  = np.nanstd(sel, axis=1)
        valid = np.abs(mean_t) > EPS
        if not np.any(valid):
            return float('inf')
        rel_pct = 100.0 * std_t[valid] / (np.abs(mean_t[valid]) + EPS)
        return float(np.nanmean(rel_pct))
    
    def combined_metric(idxs):
        """Return (combined, refl_metric, trans_metric). combined = max(refl, trans)."""
        r = channel_combined_relstd(all_refl, idxs)
        t = channel_combined_relstd(all_trans, idxs)
        return max(r, t), r, t
    
    # Map pos_token -> current index for this pulse (for quick lookup)
    token_to_idx = {pos_list[i].get('pos_token'): i for i in range(len(pos_list))}
    all_indices = list(range(npos))
    
    # If we haven't decided for this base_prefix yet (first pulse) -> find minimal-removal subset
    if base_prefix not in selection_map:
        # Quick check: if full set already meets threshold, keep all
        full_comb, full_r, full_t = combined_metric(all_indices)
        print(f"[SEL] {base_prefix} p{pulse_no}: full combined={full_comb:.2f}% (refl={full_r:.2f}%, trans={full_t:.2f}%)")
        if full_comb <= SIMILARITY_THRESHOLD_PERCENT:
            kept_idxs = all_indices.copy()
            print(f"[SEL] Keeping all {len(kept_idxs)} positions for first pulse (meets {SIMILARITY_THRESHOLD_PERCENT}%).")
        else:
            # find LARGEST subset (fewest removals) that meets threshold; exhaustive when small n
            kept_idxs = None
            found = False
            if npos <= EXHAUSTIVE_LIMIT:
                # iterate sizes from largest to MIN_KEEP
                for k in range(npos, MIN_KEEP - 1, -1):
                    for comb in combinations(range(npos), k):
                        m, rr, tt = combined_metric(list(comb))
                        if m <= SIMILARITY_THRESHOLD_PERCENT:
                            kept_idxs = sorted(list(comb))
                            found = True
                            print(f"[SEL] Found subset of size {k} meeting threshold (exhaustive).")
                            break
                    if found:
                        break
                if not found:
                    # no subset meets threshold; pick largest subset with minimal combined metric
                    best_m = float('inf')
                    best_subset = None
                    for k in range(npos, MIN_KEEP - 1, -1):
                        for comb in combinations(range(npos), k):
                            m, rr, tt = combined_metric(list(comb))
                            if m < best_m - 1e-12 or (abs(m - best_m) < 1e-12 and (best_subset is None or len(comb) > len(best_subset))):
                                best_m = m
                                best_subset = list(comb)
                    kept_idxs = sorted(best_subset)
                    print(f"[SEL-WARN] No subset reached {SIMILARITY_THRESHOLD_PERCENT}%; selecting best largest subset (size {len(kept_idxs)}) with combined={best_m:.2f}%")
            else:
                # greedy minimal-removals heuristic:
                remaining = set(all_indices)
                cur_m, cur_r, cur_t = combined_metric(sorted(remaining))
                while len(remaining) > MIN_KEEP:
                    # for each candidate removal, get metric after removal
                    best_improve = 0.0
                    best_remove = None
                    best_after = (cur_m, cur_r, cur_t)
                    for cand in list(remaining):
                        trial = sorted([i for i in remaining if i != cand])
                        m_after, r_after, t_after = combined_metric(trial)
                        improvement = cur_m - m_after
                        if improvement > best_improve + 1e-12:
                            best_improve = improvement
                            best_remove = cand
                            best_after = (m_after, r_after, t_after)
                    if best_remove is None:
                        break
                    remaining.remove(best_remove)
                    cur_m, cur_r, cur_t = best_after
                    print(f"[SEL] removed pos[{best_remove}] token={pos_list[best_remove].get('pos_token')} -> combined {cur_m:.2f}%")
                    if cur_m <= SIMILARITY_THRESHOLD_PERCENT:
                        break
                kept_idxs = sorted(remaining)
                final_m, fr, ft = combined_metric(kept_idxs)
                if final_m <= SIMILARITY_THRESHOLD_PERCENT:
                    print(f"[SEL] Greedy reached threshold with kept size {len(kept_idxs)} combined {final_m:.2f}%")
                else:
                    print(f"[SEL-WARN] Greedy couldn't reach threshold; returning best-remaining size {len(kept_idxs)} combined {final_m:.2f}%")
    
        # store the chosen pos_tokens for this base_prefix (first pulse decision)
        kept_tokens = [pos_list[i].get('pos_token') for i in kept_idxs]
        selection_map[base_prefix] = {'tokens': kept_tokens, 'kept_idxs_first': kept_idxs}
        print(f"[SEL] First-pulse selection for {base_prefix}: tokens={kept_tokens}")
    
    else:
        # not first pulse: force usage of tokens chosen earlier for this base_prefix
        desired_tokens = selection_map[base_prefix]['tokens']
        available_idxs = [token_to_idx[t] for t in desired_tokens if t in token_to_idx]
        if len(available_idxs) >= MIN_KEEP:
            kept_idxs = sorted(available_idxs)
            print(f"[SEL] Using stored tokens for {base_prefix} p{pulse_no}: kept tokens available count={len(kept_idxs)}")
        else:
            # some selected tokens missing here. keep what is available and add best others to reach MIN_KEEP
            print(f"[SEL-WARN] For {base_prefix} p{pulse_no}: only {len(available_idxs)} of the stored tokens are present. Attempting to add {MIN_KEEP - len(available_idxs)} best other positions.")
            needed = max(0, MIN_KEEP - len(available_idxs))
            candidates = [i for i in range(npos) if i not in available_idxs]
            # rank candidates by combined metric when added to currently-available set
            base_set = sorted(available_idxs)
            candidate_scores = []
            for c in candidates:
                trial = sorted(base_set + [c])
                m_after, r_after, t_after = combined_metric(trial)
                candidate_scores.append((c, m_after))
            candidate_scores.sort(key=lambda x: x[1])
            add = [c for c,_ in candidate_scores[:needed]]
            kept_idxs = sorted(base_set + add)
            print(f"[SEL] Added indices {add} to meet MIN_KEEP. Final kept indices: {kept_idxs}")

# kept_idxs now contains the indices (in pos_list) that will be averaged for this pulse
# (fall through to build mat_refl/mat_trans and write NAV as before)
# ---------------------------------------------------------------------------


    # --- from here on you can build matrices using kept_idxs as before ---
    mat_refl = np.vstack([pos_list[i]['refl'] for i in kept_idxs]).T  # shape (n_samples, n_kept)
    mat_trans = np.vstack([pos_list[i]['trans'] for i in kept_idxs]).T
    mat_laser = np.vstack([pos_list[i]['laser'] for i in kept_idxs]).T
    std_refl = np.std(mat_refl, axis=1)
    std_trans = np.std(mat_trans, axis=1)
    std_laser = np.std(mat_laser, axis=1)
    avg_refl = np.mean(mat_refl, axis=1)
    avg_trans = np.mean(mat_trans, axis=1)
    avg_laser = np.mean(mat_laser, axis=1)

    # Write nav file for this base_prefix and pulse
    base_for_nav = base_prefix
    if not base_for_nav.endswith('_'):
        base_for_nav = base_for_nav + '_'
    nav_name = f"{base_for_nav}posv_p{pulse_no}_nav.csv"
    nav_path = os.path.join(PATH, nav_name)
    if os.path.exists(nav_path):
        print(f"NAV exists for {base_prefix} p{pulse_no}: {nav_name} (skipping write)")
        skipped_nav.append(nav_name)
        continue

    time_us = (x_common * 1e6).astype(float)
    df_out = pd.DataFrame({
        'Time': time_us,
        'Channel A': avg_refl,
        'Channel B': avg_trans,
        'Channel C': avg_laser,
        'std_refl': std_refl,
        'std_trans': std_trans,
        'std_laser': std_laser
    })
    units_row = pd.DataFrame([{'Time': '(us)', 'Channel A': '(V)', 'Channel B': '(V)', 'Channel C': '(V)',
                               'std_refl': '(V)', 'std_trans': '(V)', 'std_laser': '(V)'}])
    out_df = pd.concat([units_row, df_out], ignore_index=True)
    out_df.to_csv(nav_path, index=False)
    created_nav.append(nav_name)
    kept_files = [pos_list[i].get('fname', f'file_{i}') for i in kept_idxs]
    print(f"Saved NAV: {nav_name} (averaged {len(kept_idxs)} files; omitted: {[x['fname'] for x in omit_info]})")

# ------------- plotting: read all nav files and produce 2x4 PNGs as requested --------------
# FIXED - respects FILE_PREFIXES just like all_csvs does at the top
all_nav = sorted([f for f in glob.glob('*_nav.csv')
                  if any(f.startswith(pref) for pref in FILE_PREFIXES)])
if not all_nav:
    print("No _nav.csv files found after processing; skipping plotting.")
else:
    print("\nFound _nav.csv files:", len(all_nav))
    # helper: read nav file (skip first unit row)
    def read_nav(navfile):
        d = pd.read_csv(navfile)
        if d.shape[0] < 2:
            raise ValueError(navfile + " too short")
        data = d.iloc[1:].astype(float).reset_index(drop=True)
        x = data['Time'].values * 1e-6
        refl = signal.savgol_filter(data['Channel A'].values, sampl1, poly1)
        trans = signal.savgol_filter(data['Channel B'].values, sampl1, poly1)
        s_refl = data['std_refl'].values if 'std_refl' in data.columns else np.zeros_like(x)
        s_trans = data['std_trans'].values if 'std_trans' in data.columns else np.zeros_like(x)
        return x, refl, trans, s_refl, s_trans

    # build nav metadata
    nav_meta = []
    for nav in all_nav:
        p = parse_filename(os.path.basename(nav))
        nav_meta.append({'nav': nav, 'pressure_str': p['pressure_str'], 'pressure_val': p['pressure_val'],
                         'fluence_mj': p['fluence_mj'], 'fluence_jpcm2': p['fluence_jpcm2'], 'pulse': p['pulse']})
    navdf = pd.DataFrame(nav_meta)

    # small tolerance compare for fluence floats
    def fluence_matches(a, b, tol=5e-4):
        if a is None or b is None: return False
        return abs(float(a) - float(b)) <= tol

    # Make pressure-scan figures for each requested fluence
    if MAKE_PRESSURE_SCAN_PNG:
        for fixed_f in FLUENCE_LIST_TO_PLOT_JPCM2:
            fig, axes = plt.subplots(2, 4, figsize=FIG_FIGSIZE, dpi=FIG_DPI)
            fig.subplots_adjust(hspace=0.35, wspace=0.2)
            for col_idx, pulse_no in enumerate(PULSES_TO_SHOW):
                if col_idx > 3: break
                ax_refl = axes[0, col_idx]; ax_trans = axes[1, col_idx]
                plotted_any = False
                for pstr in PRESSURE_LIST_TO_PLOT:
                    subset = navdf[(navdf['pressure_val'] == pstr) & (navdf['pulse'] == pulse_no)]
                    matched = None
                    for _, row in subset.iterrows():
                        if fluence_matches(row['fluence_jpcm2'], fixed_f):
                            matched = row; break
                    if matched is None:
                        continue
                    navfile = matched['nav']
                    x, refl, trans, sr, st = read_nav(navfile)
                    plotted_any = True
                    # plot with errorbars sparsely
                    line1 = ax_refl.plot(x*1e6, refl, label=float(pstr))[0]
                    color1 = line1.get_color()
                    if np.any(sr):
                        stride = max(1, int(ERROR_SAMPLE_FRACTION * len(x)))
                        idx = np.arange(0, len(x), stride)
                        ax_refl.errorbar(x[idx]*1e6, refl[idx], yerr=sr[idx], fmt='none',ecolor=color1, elinewidth=0.6, capsize=3)
                    
                    line2 = ax_trans.plot(x*1e6, trans, label=pstr)[0]
                    color2 = line2.get_color()
                    if np.any(st):
                        stride = max(1, int(ERROR_SAMPLE_FRACTION * len(x)))
                        idx = np.arange(0, len(x), stride)
                        ax_trans.errorbar(x[idx]*1e6, trans[idx], yerr=st[idx], fmt='none',ecolor=color2, elinewidth=0.6, capsize=3)
                if plotted_any:
                    ax_refl.set_xlabel('Time [µs]'); ax_refl.set_ylabel('Reflection (%)'); ax_refl.grid(True); ax_refl.legend(fontsize=6)
                    ax_trans.set_xlabel('Time [µs]'); ax_trans.set_ylabel('Transmission (%)'); ax_trans.grid(True); ax_trans.legend(fontsize=6)
                    ax_refl.set_title(f'Pulse {pulse_no} — Refl: (flu:={fixed_f} J/cm^2)')
                    ax_trans.set_title(f'Pulse {pulse_no} — Trans:(flu:={fixed_f} J/cm^2)')
                else:
                    ax_refl.text(0.5,0.5,'No data', transform=ax_refl.transAxes, ha='center')
                    ax_trans.text(0.5,0.5,'No data', transform=ax_trans.transAxes, ha='center')
            outname = os.path.join(PATH, f'pressure_scan_f{fixed_f}_pulses_1-4_4x2.png')
            #plt.tight_layout(); plt.savefig(outname, dpi=FIG_DPI, bbox_inches='tight', facecolor='white')
            #plt.close(fig)
            plt.show()
            #print(f"Saved pressure-scan PNG for fluence {fixed_f}: {outname}")

    # Make fluence-scan figures for each requested pressure
 # Make fluence-scan figures for each requested pressure
    if MAKE_FLUENCE_SCAN_PNG:
        for fixed_p in PRESSURE_LIST_TO_PLOT:
            fig, axes = plt.subplots(2, 4, figsize=FIG_FIGSIZE, dpi=FIG_DPI)
            fig.subplots_adjust(hspace=0.35, wspace=0.2)
            for col_idx, pulse_no in enumerate(PULSES_TO_SHOW):
                if col_idx > 3: break
                ax_refl = axes[0, col_idx]; ax_trans = axes[1, col_idx]
                plotted_any = False
    
                # robust subset selection (use fixed_p, not pstr)
                subset = get_subset_by_pressure(navdf, fixed_p)
                subset = subset[subset['pulse'] == pulse_no]
    
                for _, row in subset.iterrows():
                    fj = row['fluence_jpcm2']
                    if fj is None:
                        continue
                    navfile = row['nav']
    
                    # read and plot
                    x, refl, trans, sr, st = read_nav(navfile)
                    plotted_any = True
    
                    # format the label for nicer display
                    label_str = f"{fj:.3f} J/cm^2" if isinstance(fj, (int, float, np.floating)) else f"{fj} J/cm^2"
    
                    line3 = ax_refl.plot(x*1e6, refl, label=label_str)[0]
                    color3 = line3.get_color()
                    if np.any(sr):
                        stride = max(1, int(ERROR_SAMPLE_FRACTION * len(x)))
                        idx = np.arange(0, len(x), stride)
                        ax_refl.errorbar(x[idx]*1e6, refl[idx], yerr=sr[idx], fmt='none', ecolor=color3, elinewidth=0.6, capsize=3)
    
                    line4 = ax_trans.plot(x*1e6, trans, label=label_str)[0]
                    color4 = line4.get_color()
                    if np.any(st):
                        stride = max(1, int(ERROR_SAMPLE_FRACTION * len(x)))
                        idx = np.arange(0, len(x), stride)
                        ax_trans.errorbar(x[idx]*1e6, trans[idx], yerr=st[idx], fmt='none', ecolor=color4, elinewidth=0.6, capsize=3)
    
                if plotted_any:
                    ax_refl.set_xlabel('Time [µs]'); ax_refl.set_ylabel('Reflection (%)'); ax_refl.grid(True); ax_refl.legend(fontsize=6)
                    ax_trans.set_xlabel('Time [µs]'); ax_trans.set_ylabel('Transmission (%)'); ax_trans.grid(True); ax_trans.legend(fontsize=6)
                    ax_refl.set_title(f'Pulse {pulse_no} — Refl: (pres:={fixed_p})')
                    ax_trans.set_title(f'Pulse {pulse_no} — Trans: (pres:={fixed_p})')
                else:
                    ax_refl.text(0.5,0.5,'No data', transform=ax_refl.transAxes, ha='center')
                    ax_trans.text(0.5,0.5,'No data', transform=ax_trans.transAxes, ha='center')
    
            outname = os.path.join(PATH, f'fluence_scan_p{fixed_p}_pulses_1-4_4x2.png')
            # plt.tight_layout(); plt.savefig(outname, dpi=FIG_DPI, bbox_inches='tight', facecolor='white')
            # plt.close(fig)
            plt.show()
        # print(f"Saved fluence-scan PNG for pressure {fixed_p}: {outname}")
            plt.show()
            #print(f"Saved fluence-scan PNG for pressure {fixed_p}: {outname}")

# final summary
print("\nFinal summary:")
print("Created NAV files:", len(created_nav))
print("Skipped NAV (already existed):", len(skipped_nav))
if omitted_report:
    print("Groups with omitted positions (sample):")
    for r in omitted_report[:20]:
        print(" ", r['group'], "->", r['omitted'])
print("Done.")

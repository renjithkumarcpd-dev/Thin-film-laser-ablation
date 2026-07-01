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

import os, glob, math, re
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from scipy import signal
import scienceplots                             # noqa: F401
plt.style.use(['science'])
fig = plt.figure(0, dpi=600)
plt.rcParams['figure.dpi'] = 600   # or 600
# ── Science style ──────────────────────────────────────────────────────────────
# try:
#     import scienceplots                             # noqa: F401
#     plt.style.use(['science', 'no-latex'])
# except ImportError:
#     print("[WARN] scienceplots not installed; using default style.")

# matplotlib.rcParams.update({
#     'text.usetex'       : False,
#     'font.family'       : 'serif',
#     'axes.grid'         : True,
#     'grid.alpha'        : 0.5,
#     'grid.linewidth'    : 0.4,
#     'xtick.direction'   : 'in',
#     'ytick.direction'   : 'in',
#     'xtick.top'         : True,
#     'ytick.right'       : True,
#     'legend.frameon'    : True,
#     'legend.framealpha' : 0.7,
# })

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                        USER CONFIGURATION                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

# ── Search paths ──────────────────────────────────────────────────────────────
PATHS = [
    r'D:\renjith_phD\Renjith_laser_data\Data collected directly\Silver_400nm_film',
    r'D:\renjith_phD\Renjith_laser_data\Data collected directly\Silver_200nm_film',
    r'D:\renjith_phD\Renjith_laser_data\Data collected directly\Aluminium_200nm_film',
    r'D:\renjith_phD\Renjith_laser_data\Data collected directly\Aluminium_400nm_film',
    #r'D:\renjith_phD\Renjith_laser_data\Data collected directly\27032026',
    #r'D:\renjith_phD\Renjith_laser_data\Data collected directly\06042026',
    #r'D:\renjith_phD\Renjith_laser_data\Data collected directly\02042026',
    #r'D:\renjith_phD\Renjith_laser_data\Data collected directly\07042026',
    
]

# ── Fixed parameters ───────────────────────────────────────────────────────────
# OPTION A — single dict → produces ONE figure:
#   FIXED = {'prefix': 'a4', 'orientation': None, ...}
#
# OPTION B — list of dicts → produces ONE SEPARATE FIGURE per entry:
#   FIXED = [
#       {'prefix': 'a4', 'orientation': 'fa', ...},
#       {'prefix': 'a4', 'orientation': 'fp', ...},
#   ]
#
# Set any value to None to let that parameter vary freely in that figure.

FIXED = [
    {
        'prefix'      : None,
        'orientation' : None,
        'wavelength'  : '1064nm',
        'pressure'    : '100e+1mbar',
        'energy'      : None,
        'pulse_width' : '*us',
        'pulse'       : None,
    }
    # {
    #     'prefix'      : 'a4',
    #     'orientation' : 'fp',
    #     'wavelength'  : '1064nm',
    #     'pressure'    : '100e+0mbar',
    #     'energy'      : '060mj',
    #     'pulse_width' : '0*us',
    #     'pulse'       : None,
    # },
]

# ── Restrict varying parameters to specific values (None / [] = all found) ────
FILTER = {
    'pulse'       : [1,2],
    'orientation' : ['bp'],
    'pressure'    : None,
    'energy'      : ['60mj','120mj'],
    'prefix'      : ['a2','a4','s2','s4'],
    'pulse_width' : ['010us','005us'],
}

# ── Plot mode ─────────────────────────────────────────────────────────────────
# 'R'  |  'T'  |  'R|T'  |  'overlay'  |  'sum'  |  'absorption'  |  'all'
PLOT_MODE = 'R|T'

# ── Layout ────────────────────────────────────────────────────────────────────
LAYOUT     = 'grid'
GRID_PARAM = 'pulse'

# ── Legend params — None = auto-detect from what actually varies ──────────────
LEGEND_PARAMS = None

# ── Smoothing ─────────────────────────────────────────────────────────────────
# (window, poly) — window must be odd; even values are auto-corrected.
# Option A — same for all curves:   SMOOTHING = (201, 1)
# Option B — per curve list:        SMOOTHING = [(201,1), (101,1), (51,1), (1,0)]
# Option C — dict by key:           SMOOTHING = {1:(201,1), 2:(101,1), 'fa':(51,1)}
SMOOTHING = (20, 1)

SHOW_SMOOTHING_IN_LEGEND = True

# ── Human-readable labels ─────────────────────────────────────────────────────
PREFIX_LABELS = {
    's4':'Ag 400nm', 's2':'Ag 200nm',
    'a4':'Al 400nm', 'a2':'Al 200nm',
    'ca':'Carbon',
}
ORIENT_LABELS = {
    'fa':'FA FP', 'fp':'FA RP',
    'ba':'RA RP', 'bp':'RA FP',
}

# ── Colour / linestyle cycles ─────────────────────────────────────────────────
COLORS = [
    'b', 'violet', 'y', 'c', 'm', 'r', 'k', 'g',
    'orange', 'brown', 'pink', 'gray', 'navy', 'lime'
]
LINESTYLES = ['-', '--', '-.', ':']

# ── Error bars ────────────────────────────────────────────────────────────────
SHOW_ERRORBARS    = True
ERROR_BAR_START   = 0.10
ERROR_BAR_END     = 0.90
ERROR_BAR_SPACING = 0.08

# ── Axis limits (µs / %) — None = auto ───────────────────────────────────────
X_LIMIT       = [-5,80]
Y_LIMIT_REFL  = None
Y_LIMIT_TRANS = None
Y_LIMIT_SUM   = None
Y_LIMIT_ABS   = None

# ── Figure ────────────────────────────────────────────────────────────────────
FIG_FIGSIZE     = (16, 8)
FIG_DPI         = 600       # passed directly to plt.subplots — same as reference code
LEGEND_FONTSIZE = 8.0

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                            HELPERS                                       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def mj_to_jpcm2(mj_val):
    try:
        return round(2 * float(mj_val) * 1e-3 / (math.pi * 0.05**2), 1)
    except Exception:
        return None

def parse_num(token):
    if token is None: return None
    m = re.search(r'([-+]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)', str(token))
    return float(m.group(1)) if m else None

# ── Auto-correct even window to nearest odd ───────────────────────────────────
def _fix_even_window(s):
    if isinstance(s, tuple):
        w, p = s
        return (w + 1 if w > 1 and w % 2 == 0 else w, p)
    if isinstance(s, list):
        return [_fix_even_window(t) for t in s]
    if isinstance(s, dict):
        return {k: _fix_even_window(v) for k, v in s.items()}
    return s

SMOOTHING = _fix_even_window(SMOOTHING)

def _resolve_smoothing(record, curve_idx):
    s = SMOOTHING
    if isinstance(s, tuple): return s
    if isinstance(s, list):  return s[min(curve_idx, len(s)-1)]
    if isinstance(s, dict):
        for key in (record.get('pulse'), record.get('orientation'),
                    record.get('prefix'), record.get('pressure')):
            if key in s: return s[key]
        return next(iter(s.values()))
    return (1, 0)

def _smoothing_varies():
    s = SMOOTHING
    if isinstance(s, tuple): return False
    if isinstance(s, list):  return len(set(s)) > 1
    if isinstance(s, dict):  return len(set(s.values())) > 1
    return False

def do_smooth(arr, window, poly):
    if window and window >= 3:
        if window % 2 == 0:
            window += 1
        if window <= len(arr):
            return signal.savgol_filter(arr, window, poly)
    return arr.copy()

# ── File I/O ──────────────────────────────────────────────────────────────────
def read_nav(filepath, window, poly):
    df   = pd.read_csv(filepath)
    data = df.iloc[1:].astype(float).reset_index(drop=True)
    x    = data['Time'].values
    r    = do_smooth(data['Channel A'].values, window, poly)
    t    = do_smooth(data['Channel B'].values, window, poly)
    sr   = data['std_refl'].values  if 'std_refl'  in data.columns else np.zeros_like(x)
    st   = data['std_trans'].values if 'std_trans' in data.columns else np.zeros_like(x)
    return x, r, t, sr, st

def parse_filename(fname):
    base  = os.path.basename(fname)
    parts = base.replace('_nav.csv', '').split('_')
    info  = {'filepath': fname, 'basename': base}
    info['prefix']      = parts[0] if parts else None
    orient_set          = {'fa', 'fp', 'ba', 'bp'}
    info['orientation'] = next((p.lower() for p in parts if p.lower() in orient_set), None)

    def _tok(pattern):
        m = re.search(pattern, base, re.I)
        return m.group(1).lower() if m else None

    info['wavelength']   = _tok(r'(\d+nm)')
    info['pressure']     = _tok(r'([-+]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?mbar)')
    info['pressure_val'] = parse_num(info['pressure'])
    info['energy']       = _tok(r'(\d+mj)')
    info['energy_val']   = parse_num(info['energy'])
    info['fluence']      = mj_to_jpcm2(info['energy_val'])
    info['pulse_width']  = _tok(r'(\d+us)')
    m = re.search(r'_p(\d+)_nav', base, re.I)
    info['pulse'] = int(m.group(1)) if m else None
    return info

# ── Legend builder ────────────────────────────────────────────────────────────
def make_label(info, legend_params, window=None, poly=None):
    parts = []
    for param in legend_params:
        if   param == 'prefix'      : parts.append(PREFIX_LABELS.get(info['prefix'], info['prefix'] or ''))
        elif param == 'orientation'  : parts.append(ORIENT_LABELS.get(info['orientation'], info['orientation'] or ''))
        elif param == 'pressure'     :
            v = info.get('pressure_val')
            parts.append(f"{v:.4g} mbar" if v is not None else str(info.get('pressure', '')))
        elif param == 'energy'       :
            f = info.get('fluence')
            parts.append(f"{f} J/cm\u00b2" if f is not None else str(info.get('energy', '')))
        elif param == 'pulse'        : parts.append(f"p{info['pulse']}")
        elif param == 'pulse_width'  : parts.append(str(info.get('pulse_width', '')))
    if SHOW_SMOOTHING_IN_LEGEND and _smoothing_varies() and window is not None:
        parts.append(f"w={window}" if window >= 3 else "no-smooth")
    return ', '.join(parts) if parts else info['basename']

# ── Plot utilities ────────────────────────────────────────────────────────────
def plot_errorbars(ax, x, y, yerr, color):
    if not SHOW_ERRORBARS or not np.any(yerr): return
    x_lo = X_LIMIT[0] if X_LIMIT else x.min()
    x_hi = X_LIMIT[1] if X_LIMIT else x.max()
    idx  = np.where((x >= x_lo) & (x <= x_hi))[0]
    if not len(idx): return
    start = idx[int(len(idx) * ERROR_BAR_START)]
    end   = idx[int(len(idx) * ERROR_BAR_END)]
    step  = max(1, int(len(idx) * ERROR_BAR_SPACING))
    for i in range(start, end, step):
        ax.errorbar(x[i], y[i], yerr=yerr[i], fmt='none',
                    color=color, elinewidth=0.7, capsize=2.5, capthick=0.7)

def apply_limits(ax, xlim, ylim):
    if xlim: ax.set_xlim(xlim)
    if ylim: ax.set_ylim(ylim)
    ax.axhline(0, color='k', lw=0.4, ls='--', alpha=0.4)

def draw_curve(ax, x, y, yerr, color, ls, label):
    ax.plot(x, y, color=color, ls=ls, lw=0.9, label=label)
    plot_errorbars(ax, x, y, yerr, color)

# ── Filter ────────────────────────────────────────────────────────────────────
def passes_filter(info):
    for param, allowed in FILTER.items():
        if not allowed: continue
        val = info.get(param)
        if param == 'pulse':
            if val not in [int(a) for a in allowed]: return False
        elif param in ('pressure', 'energy'):
            tv    = info.get(f'{param}_val')
            anums = [parse_num(str(a)) for a in allowed]
            if not any(tv is not None and abs(tv - an) < 1e-6
                       for an in anums if an is not None): return False
        else:
            if str(val) not in [str(a) for a in allowed]: return False
    return True

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║              PER-FIXED FIGURE BUILDER                                    ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def _ftok(fixed, key):
    v = fixed.get(key)
    return '*' if v is None else str(v)

def build_title(fixed):
    PARAM_KEYS  = ['prefix', 'orientation', 'pressure', 'energy',
                   'pulse', 'pulse_width', 'wavelength']
    title_parts = []
    for k in PARAM_KEYS:
        v = fixed.get(k)
        if v is None: continue
        if   k == 'prefix'      : title_parts.append(PREFIX_LABELS.get(str(v), str(v)))
        elif k == 'orientation'  : title_parts.append(ORIENT_LABELS.get(str(v), str(v)))
        elif k == 'pressure'     : title_parts.append(f"{parse_num(str(v)):.4g} mbar")
        elif k == 'energy'       : title_parts.append(f"{mj_to_jpcm2(parse_num(str(v)))} J/cm\u00b2")
        elif k == 'pulse'        : title_parts.append(f"p{v}")
        elif k == 'wavelength'   : title_parts.append(str(v))
    if not _smoothing_varies() and isinstance(SMOOTHING, tuple):
        w, p = SMOOTHING
        title_parts.append(f"Savgol w={w}, poly={p}" if w >= 3 else "no smoothing")
    return '  |  '.join(title_parts)

def make_figure(fixed, fig_number, total_figs):
    """Discover files, filter, and draw one complete figure for a given FIXED dict."""

    # ── File discovery ────────────────────────────────────────────────────────
    print(f"\n── Figure {fig_number}/{total_figs}: FIXED = {fixed} ──")
    all_records = []
    for folder in PATHS:
        if not os.path.isdir(folder):
            print(f"  [SKIP] {folder}"); continue
        pulse_glob = '*' if fixed.get('pulse') is None else str(fixed['pulse'])
        pattern = os.path.join(
            folder,
            f"{_ftok(fixed,'prefix')}_{_ftok(fixed,'orientation')}_{_ftok(fixed,'wavelength')}"
            f"_{_ftok(fixed,'pressure')}_{_ftok(fixed,'energy')}_{_ftok(fixed,'pulse_width')}"
            f"_posv_p{pulse_glob}_nav.csv"
        )
        for f in sorted(glob.glob(pattern)):
            all_records.append(parse_filename(f))

    records = [r for r in all_records if passes_filter(r)]
    print(f"  Found {len(all_records)} total → kept {len(records)} after filters")
    for r in records:
        print(f"    {r['basename']}")

    if not records:
        print("  [SKIP] No files found — skipping this figure.")
        return

    # ── Auto-detect varying params ────────────────────────────────────────────
    PARAM_KEYS    = ['prefix', 'orientation', 'pressure', 'energy', 'pulse', 'pulse_width']
    varying       = [k for k in PARAM_KEYS
                     if fixed.get(k) is None and len({str(r.get(k)) for r in records}) > 1]
    legend_params = LEGEND_PARAMS if LEGEND_PARAMS else varying
    if not legend_params:
        legend_params = ['orientation']

    print(f"  Varying          : {varying}")
    print(f"  Legend will show : {legend_params}")

    records.sort(key=lambda r: (
        str(r.get('prefix') or ''),
        str(r.get('orientation') or ''),
        r.get('pressure_val') or 0,
        r.get('energy_val') or 0,
        r.get('pulse') or 0,
    ))

    TITLE = build_title(fixed)
    XLBL  = r'Time [$\mu$s]'

    # ── GRID LAYOUT ───────────────────────────────────────────────────────────
    if LAYOUT == 'grid' and PLOT_MODE == 'R|T':
        grid_vals = sorted({r.get(GRID_PARAM) for r in records
                            if r.get(GRID_PARAM) is not None})
        if not grid_vals:
            raise ValueError(f"GRID_PARAM='{GRID_PARAM}' has no values in filtered records.")

        n_cols = len(grid_vals)
        # DPI passed directly to subplots — identical to reference code
        fig, axes = plt.subplots(2, n_cols, figsize=FIG_FIGSIZE, dpi=FIG_DPI, squeeze=False)
        fig.subplots_adjust(hspace=0.38, wspace=0.28)
        fig.suptitle(TITLE, fontsize=9, y=1.01)

        sub_legend = [p for p in legend_params if p != GRID_PARAM] or ['orientation']
        global_idx = 0

        for col, gval in enumerate(grid_vals):
            ax_r = axes[0, col]
            ax_t = axes[1, col]
            col_records = [r for r in records if r.get(GRID_PARAM) == gval]

            col_title_map = {
                'pulse'       : f"Pulse {gval}",
                'pressure'    : f"{parse_num(str(gval)):.4g} mbar",
                'energy'      : f"{mj_to_jpcm2(parse_num(str(gval)))} J/cm\u00b2",
                'orientation' : ORIENT_LABELS.get(str(gval), str(gval)),
            }
            col_title = col_title_map.get(GRID_PARAM, str(gval))

            for local_idx, rec in enumerate(col_records):
                color     = COLORS[local_idx % len(COLORS)]
                ls        = LINESTYLES[local_idx // len(COLORS) % len(LINESTYLES)]
                win, poly = _resolve_smoothing(rec, global_idx)
                x, refl, trans, sr, st = read_nav(rec['filepath'], win, poly)
                lbl = make_label(rec, sub_legend, win, poly)
                draw_curve(ax_r, x, refl,  sr, color, ls, f"R: {lbl}")
                draw_curve(ax_t, x, trans, st, color, ls, f"T: {lbl}")
                global_idx += 1

            ax_r.set_title(col_title, fontsize=8)
            ax_r.set_ylabel('Reflection ($\%$)', fontsize=7)
            ax_r.set_xlabel(XLBL, fontsize=7)
            ax_r.legend(fontsize=LEGEND_FONTSIZE)
            apply_limits(ax_r, X_LIMIT, Y_LIMIT_REFL)

            ax_t.set_ylabel('Transmission ($\%$)', fontsize=7)
            ax_t.set_xlabel(XLBL, fontsize=7)
            ax_t.legend(fontsize=LEGEND_FONTSIZE)
            apply_limits(ax_t, X_LIMIT, Y_LIMIT_TRANS)

    # ── AUTO LAYOUT ───────────────────────────────────────────────────────────
    else:
        n_panels = {'R':1,'T':1,'R|T':2,'overlay':1,'sum':1,'absorption':1,'all':3}.get(PLOT_MODE, 1)
        fig, axes_row = plt.subplots(1, n_panels,
                                     figsize=(max(5, 5*n_panels), 4.5),
                                     dpi=FIG_DPI, squeeze=False)
        af = axes_row[0]
        fig.suptitle(TITLE, fontsize=9)

        for curve_idx, rec in enumerate(records):
            color     = COLORS[curve_idx % len(COLORS)]
            ls        = LINESTYLES[curve_idx // len(COLORS) % len(LINESTYLES)]
            win, poly = _resolve_smoothing(rec, curve_idx)
            x, refl, trans, sr, st = read_nav(rec['filepath'], win, poly)
            lbl = make_label(rec, legend_params, win, poly)

            if PLOT_MODE == 'R':
                draw_curve(af[0], x, refl, sr, color, ls, lbl)
            elif PLOT_MODE == 'T':
                draw_curve(af[0], x, trans, st, color, ls, lbl)
            elif PLOT_MODE == 'R|T':
                draw_curve(af[0], x, refl,  sr, color, ls, f"R: {lbl}")
                draw_curve(af[1], x, trans, st, color, ls, f"T: {lbl}")
            elif PLOT_MODE == 'overlay':
                af[0].plot(x, refl,  color=color, ls='-',  lw=0.9, label=f"R: {lbl}")
                af[0].plot(x, trans, color=color, ls='--', lw=0.9, label=f"T: {lbl}")
                plot_errorbars(af[0], x, refl,  sr, color)
                plot_errorbars(af[0], x, trans, st, color)
            elif PLOT_MODE == 'sum':
                draw_curve(af[0], x, refl+trans,
                           np.sqrt(sr**2+st**2), color, ls, lbl)
            elif PLOT_MODE == 'absorption':
                draw_curve(af[0], x, 100.0-refl-trans,
                           np.sqrt(sr**2+st**2), color, ls, lbl)
            elif PLOT_MODE == 'all':
                draw_curve(af[0], x, refl,             sr,                    color, ls, lbl)
                draw_curve(af[1], x, trans,             st,                    color, ls, lbl)
                draw_curve(af[2], x, 100.0-refl-trans,  np.sqrt(sr**2+st**2), color, ls, lbl)

        specs = {
            'R'         : (['Reflection (%)'],                              [Y_LIMIT_REFL]),
            'T'         : (['Transmission (%)'],                            [Y_LIMIT_TRANS]),
            'R|T'       : (['Reflection (%)','Transmission (%)'],           [Y_LIMIT_REFL, Y_LIMIT_TRANS]),
            'overlay'   : (['Signal (%)'],                                  [None]),
            'sum'       : (['R + T (%)'],                                   [Y_LIMIT_SUM]),
            'absorption': ([u'Absorption  100\u2212R\u2212T (%)'],          [Y_LIMIT_ABS]),
            'all'       : (['Reflection (%)','Transmission (%)','Absorption (%)'],
                           [Y_LIMIT_REFL, Y_LIMIT_TRANS, Y_LIMIT_ABS]),
        }
        yl_labels, yl_limits = specs[PLOT_MODE]
        for i, ax in enumerate(af):
            ax.set_ylabel(yl_labels[i] if i < len(yl_labels) else '', fontsize=8)
            ax.set_xlabel(XLBL, fontsize=8)
            apply_limits(ax, X_LIMIT, yl_limits[i] if i < len(yl_limits) else None)
            ax.legend(fontsize=LEGEND_FONTSIZE)

    #plt.tight_layout()
    #plt.show()
    print(f"  Done — {len(records)} curves plotted.")


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                        MAIN — iterate over FIXED                         ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

# Normalise: wrap a single dict in a list so the loop always works
fixed_list = FIXED if isinstance(FIXED, list) else [FIXED]

for i, fixed_entry in enumerate(fixed_list):
    print(f"\n{'='*60}")
    print(f"  Figure {i+1} of {len(fixed_list)}")
    print(f"{'='*60}")
    make_figure(fixed_entry, fig_number=i+1, total_figs=len(fixed_list))

print("\nAll figures done.")

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                        QUICK RECIPE GUIDE                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
"""
── RECIPE 1: Single figure, grid of pulses ───────────────────────────────────
    FIXED = {'prefix':'a4', 'orientation':None, 'wavelength':'1064nm',
             'pressure':'100e+0mbar', 'energy':'060mj',
             'pulse_width':'0*us', 'pulse':None}
    FILTER = {'orientation':['fa','fp'], 'pulse':[1,2,3,4]}
    PLOT_MODE='R|T'  LAYOUT='grid'  GRID_PARAM='pulse'

── RECIPE 2: Two separate figures (FA vs FP) — no overplotting ───────────────
    FIXED = [
        {'prefix':'a4','orientation':'fa','wavelength':'1064nm',
         'pressure':'100e+0mbar','energy':'060mj','pulse_width':'0*us','pulse':None},
        {'prefix':'a4','orientation':'fp','wavelength':'1064nm',
         'pressure':'100e+0mbar','energy':'060mj','pulse_width':'0*us','pulse':None},
    ]

── RECIPE 3: Four separate figures, one per pulse ────────────────────────────
    FIXED = [
        {'prefix':'a4','orientation':None,'wavelength':'1064nm',
         'pressure':'100e+0mbar','energy':'060mj','pulse_width':'0*us','pulse':p}
        for p in [1, 2, 3, 4]
    ]

── RECIPE 4: Pressure scan ───────────────────────────────────────────────────
    FIXED = {'prefix':'a4','orientation':'fa','pressure':None,
             'wavelength':'1064nm','energy':'060mj','pulse_width':'0*us','pulse':None}
    FILTER = {'pressure':['100e+0mbar','500e+0mbar','1000e+0mbar']}
    LEGEND_PARAMS = ['pressure']

── RECIPE 5: Fluence scan ────────────────────────────────────────────────────
    FIXED = {'prefix':'a4','orientation':'fa','energy':None,
             'wavelength':'1064nm','pressure':'100e+0mbar','pulse_width':'0*us','pulse':None}
    FILTER = {'energy':['040mj','060mj','080mj']}
    LEGEND_PARAMS = ['energy']

── RECIPE 6: Material comparison, single figure ─────────────────────────────
    FIXED = {'prefix':None,'orientation':'fa','pressure':'100e+0mbar',
             'energy':'060mj','pulse_width':'0*us','pulse':1,'wavelength':'1064nm'}
    FILTER = {'prefix':['a4','s4']}
    LEGEND_PARAMS = ['prefix']
"""
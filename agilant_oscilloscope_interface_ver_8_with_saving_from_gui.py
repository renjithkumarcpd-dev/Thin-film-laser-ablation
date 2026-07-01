# -*- coding: utf-8 -*-
"""
Created on Sat Dec 13 16:56:21 2025
This will work with shutter translation ver 9 of arduino program
This may contain several errors that has to be addressed properly
Author: PLEXTEK + ChatGPT edits
"""
import tkinter as tk
from tkinter import messagebox, scrolledtext
import serial, threading, time, json, os

# import the oscilloscope module you updated above
# ensure this module exposes:
#   - collect_waveform_and_save_once(...)
#   - discover_and_open(scope_ip, timeout_ms)
#   - DEFAULT_SCOPE_IP, GLOBAL_TOUT, DEFAULT_POINTS, BASE_DIRECTORY, BASE_FILE_NAME
import agilant_oscilloscope_interface_ver_6_with_saving_from_gui as ic

PORT = 'COM3'
BAUD = 115200
PREFS_FILE = os.path.join(os.path.expanduser('~'), '.stage_gui_prefs.json')

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Stage Controller")
        self.conn = None
        self._waiting_for_line = False   # flag to coordinate serial reader vs waiting function
        self._stop_requested = False
        self._build()
        self.load_prefs()
        # ensure prefs saved on exit
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _build(self):
        # ---------------- main container ----------------
        pad = dict(padx=6, pady=4)
        main = tk.Frame(self)
        main.pack(padx=10, pady=8, fill='x')

        # --- Left column: stage sequence parameters ---
        left = tk.LabelFrame(main, text="Sequence", padx=6, pady=6)
        left.grid(row=0, column=0, sticky='nw', **pad)

        labels = ["No of pos: (>0)","No: of pulses","Dist X mm","Dist Z mm"]
        self.vars = {}
        for i, lbl in enumerate(labels):
            tk.Label(left, text=lbl).grid(row=i, column=0, sticky='e')
            e = tk.Entry(left, width=10)
            e.grid(row=i, column=1, sticky='w', **pad)
            self.vars[lbl] = e

        # Directions for sequence (keeps original controls)
        tk.Label(left, text="Dir X").grid(row=4, column=0, sticky='e')
        self.dx = tk.StringVar(value='F')
        tk.OptionMenu(left, self.dx, 'F', 'B').grid(row=4, column=1, sticky='w')

        tk.Label(left, text="Dir Z").grid(row=5, column=0, sticky='e')
        self.dz = tk.StringVar(value='F')
        tk.OptionMenu(left, self.dz, 'F', 'B').grid(row=5, column=1, sticky='w')

        # Use oscilloscope checkbox
        self.scope_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(left, text="Use Oscilloscope", variable=self.scope_enabled).grid(row=6, column=0, columnspan=2, sticky='w', **pad)

        # Connect / Start / Collect / Emergency Stop
        btn_row = 7
        tk.Button(left, text="Connect", command=self.connect, width=10).grid(row=btn_row, column=0, **pad)
        tk.Button(left, text="Start",   command=self.start,   width=10).grid(row=btn_row, column=1, **pad)
        tk.Button(left, text="Collect & Save", command=self.start_collection_thread, width=14).grid(row=btn_row+1, column=0, columnspan=2, pady=(6,0))
        tk.Button(left, text="EMERGENCY STOP", command=self.emergency_stop, width=14, bg="#FF4444", fg="white").grid(row=btn_row+2, column=0, columnspan=2, pady=(8,0))

        # -------------- Right column: metadata -------------
        right = tk.LabelFrame(main, text="Metadata (for filename)", padx=6, pady=6)
        right.grid(row=0, column=1, sticky='ne', **pad)

        # First row (prefix + wavelength)
        tk.Label(right, text="Prefix (4 chars)").grid(row=0, column=0, sticky='e')
        self.prefix_entry = tk.Entry(right, width=14)
        self.prefix_entry.grid(row=0, column=1, sticky='w', **pad)

        tk.Label(right, text="Wavelength").grid(row=0, column=2, sticky='e')
        self.wavelength_entry = tk.Entry(right, width=12)
        self.wavelength_entry.grid(row=0, column=3, sticky='w', **pad)

        # Second row (pressure + energy)
        tk.Label(right, text="Pressure (string)").grid(row=1, column=0, sticky='e')
        self.pressure_entry = tk.Entry(right, width=14)
        self.pressure_entry.grid(row=1, column=1, sticky='w', **pad)

        tk.Label(right, text="Energy (mJ)").grid(row=1, column=2, sticky='e')
        self.energy_entry = tk.Entry(right, width=8)
        self.energy_entry.grid(row=1, column=3, sticky='w', **pad)

        # Third row (timescale)
        tk.Label(right, text="Timescale (us)").grid(row=2, column=0, sticky='e')
        self.timescale_entry = tk.Entry(right, width=10)
        self.timescale_entry.grid(row=2, column=1, sticky='w', **pad)

        # -------------- Manual Shutter Control (NEW) -------------
        shutter_f = tk.LabelFrame(self, text="Manual Shutter (Inspection/Alignment Only)", padx=6, pady=6)
        shutter_f.pack(padx=10, pady=(4,4), fill='x')
        
        tk.Label(shutter_f, text="⚠ Use only when NOT running Q-switch sequence", 
                 fg="red", font=("Arial", 9, "bold")).pack(pady=2)
        
        shutter_btn_frame = tk.Frame(shutter_f)
        shutter_btn_frame.pack(pady=4)
        
        tk.Button(shutter_btn_frame, text="OPEN Shutter", 
                 command=self.manual_open_shutter, 
                 bg="#90EE90", width=15).pack(side='left', padx=4)
        tk.Button(shutter_btn_frame, text="CLOSE Shutter", 
                 command=self.manual_close_shutter, 
                 bg="#FFB6C1", width=15).pack(side='left', padx=4)

        # Shutter indicator
        self.shutter_indicator = tk.Label(shutter_f, text="Shutter: UNKNOWN", bg="#CCCCCC", width=20)
        self.shutter_indicator.pack(pady=(6,0))

        # -------------- Manual Move Frame (below) -------------
        manual_f = tk.LabelFrame(self, text="Manual Move", padx=6, pady=6)
        manual_f.pack(padx=10, pady=(4,8), fill='x')

        tk.Label(manual_f, text="X dist mm").grid(row=0, column=0, sticky='e')
        self.manual = {}
        e_x = tk.Entry(manual_f, width=10); e_x.grid(row=0, column=1, sticky='w', **pad)
        self.manual['X'] = e_x
        dir_x = tk.StringVar(value='F'); setattr(self, "dir_X", dir_x)
        tk.OptionMenu(manual_f, dir_x, 'F', 'B').grid(row=0, column=2)
        tk.Button(manual_f, text="Move X", command=lambda: self.move_axis('X'), width=10).grid(row=0, column=3, padx=8)

        tk.Label(manual_f, text="Z dist mm").grid(row=1, column=0, sticky='e')
        e_z = tk.Entry(manual_f, width=10); e_z.grid(row=1, column=1, sticky='w', **pad)
        self.manual['Z'] = e_z
        dir_z = tk.StringVar(value='F'); setattr(self, "dir_Z", dir_z)
        tk.OptionMenu(manual_f, dir_z, 'F', 'B').grid(row=1, column=2)
        tk.Button(manual_f, text="Move Z", command=lambda: self.move_axis('Z'), width=10).grid(row=1, column=3, padx=8)

        # -------------- Log area (bottom) -------------
        self.log = scrolledtext.ScrolledText(self, height=10, state='disabled')
        self.log.pack(fill='both', padx=10, pady=(0,10))

    # ---------------- NEW: Manual Shutter Control Methods ----------------
    def manual_open_shutter(self):
        """Send command to Arduino to open shutter manually (no Q-switch waiting)"""
        if not self.conn:
            messagebox.showwarning("Not connected", "Please connect first")
            return
        
        # Confirmation dialog to prevent accidental laser exposure
        if not messagebox.askyesno("Confirm", 
                                   "Open shutter manually?\n\nWARNING: Only use for inspection/alignment when laser is OFF or Q-switch is disabled."):
            return
        
        try:
            cmd = "MANUAL_OPEN\n"
            self.conn.write(cmd.encode())
            self._log(f"> {cmd.strip()} (Manual shutter open)")
            # update indicator immediately (best-effort)
            self._set_shutter_indicator(True)
            self.save_prefs()
        except Exception as e:
            messagebox.showerror("Serial Error", f"Failed to send command: {e}")
    
    def manual_close_shutter(self):
        """Send command to Arduino to close shutter manually"""
        if not self.conn:
            messagebox.showwarning("Not connected", "Please connect first")
            return
        
        try:
            cmd = "MANUAL_CLOSE\n"
            self.conn.write(cmd.encode())
            self._log(f"> {cmd.strip()} (Manual shutter close)")
            # update indicator
            self._set_shutter_indicator(False)
            self.save_prefs()
        except Exception as e:
            messagebox.showerror("Serial Error", f"Failed to send command: {e}")

    def _set_shutter_indicator(self, is_open: bool):
        if is_open:
            self.shutter_indicator.config(text="Shutter: OPEN", bg="#90EE90")
        else:
            self.shutter_indicator.config(text="Shutter: CLOSED", bg="#FFB6C1")

    # ---------------- rest of class unchanged (mostly) ----------------
    def connect(self):
        try:
            self.conn = serial.Serial(PORT, BAUD, timeout=0.1)
        except Exception as e:
            messagebox.showerror("Serial error", f"Failed to open {PORT}: {e}")
            return
        time.sleep(2)
        threading.Thread(target=self._reader, daemon=True).start()
        self._log(f"Connected to {PORT}")

    def start(self):
        if not self.conn:
            messagebox.showwarning("Not conn","Please connect first")
            return
        vals = [self.vars[k].get() for k in ["No of pos: (>0)","No: of pulses","Dist X mm","Dist Z mm"]]
        cmd = "SEQ," + ",".join(vals + [self.dx.get(), self.dz.get()]) + "\n"
        self.conn.write(cmd.encode()); self._log(f"> {cmd.strip()}")
        self.save_prefs()

    def move_axis(self, axis):
        if not self.conn:
            messagebox.showwarning("Not conn","Please connect first")
            return
        dist = self.manual[axis].get()
        dir_val = getattr(self, f"dir_{axis}").get()
        cmd = f"MOV,{axis},{dist},{dir_val}\n"
        self.conn.write(cmd.encode())
        self._log(f"> {cmd.strip()}")
        self.save_prefs()

    def _reader(self):
        """Background serial reader that logs asynchronous messages.
           It avoids reading while _wait_for_line is active (handshake section)."""
        while True:
            try:
                if not self.conn:
                    time.sleep(0.1)
                    continue
                # when waiting for a specific line, let the waiting function read it
                if self._waiting_for_line:
                    time.sleep(0.05)
                    continue
                if self.conn.in_waiting:
                    line = self.conn.readline().decode(errors='ignore').strip()
                    if line:
                        self._log(f"< {line}")
                        # simple heuristic: update shutter indicator if Arduino reports it
                        l = line.upper()
                        if 'SHUTTER' in l and 'OPEN' in l:
                            self._set_shutter_indicator(True)
                        elif 'SHUTTER' in l and ('CLOSE' in l or 'CLOSED' in l):
                            self._set_shutter_indicator(False)
                else:
                    time.sleep(0.05)
            except Exception:
                time.sleep(0.1)

    def _log(self,msg):
        self.log.config(state='normal')
        self.log.insert('end', msg+'\n')
        self.log.yview('end')
        self.log.config(state='disabled')

    def start_collection_thread(self):
        # reset stop flag and start collection
        self._stop_requested = False
        t = threading.Thread(target=self.collection_sequence, daemon=True)
        t.start()

    # ---------- new helpers for handshake and reading ----------
    def _wait_for_specific(self, prefixes, timeout=20.0):
        """Wait for a serial line starting with any of prefixes (list) and return the full line.
           Returns None on timeout or if emergency stop requested. While waiting background _reader is suspended from consuming data.
        """
        if not self.conn:
            return None
        self._waiting_for_line = True
        try:
            t0 = time.time()
            while time.time() - t0 < timeout:
                if self._stop_requested:
                    return None
                try:
                    if self.conn.in_waiting:
                        line = self.conn.readline().decode(errors='ignore').strip()
                        if not line:
                            continue
                        self._log(f"< {line}")
                        for p in prefixes:
                            if line.startswith(p):
                                return line
                        # if not matched, keep looping (other messages may appear)
                    else:
                        time.sleep(0.01)
                except Exception:
                    time.sleep(0.01)
            return None
        finally:
            self._waiting_for_line = False

    # ---------- main collection sequence with handshake ----------
    def collection_sequence(self):
        if not self.conn:
            messagebox.showwarning("Not conn","Please connect first")
            return

        try:
            npos = int(self.vars["No of pos: (>0)"].get())
            npulses = int(self.vars["No: of pulses"].get())
        except Exception:
            messagebox.showerror("Bad values", "Please enter integer values for number of positions and pulses.")
            return

        first4 = (self.prefix_entry.get() or "").strip()
        wavelength = (self.wavelength_entry.get() or "").strip() or "1064nm"
        pressure = (self.pressure_entry.get() or "").strip() or "100mbar"
        energy = (self.energy_entry.get() or "0").strip() or "0"
        timescale = (self.timescale_entry.get() or "1").strip() or "1"

        # --- ensure date-based subfolder inside BASE_DIRECTORY ---
        from datetime import datetime
        date_folder = datetime.now().strftime('%d%m%Y')  # e.g. 20012026
        outdir = os.path.join(ic.BASE_DIRECTORY, date_folder)
        try:
            os.makedirs(outdir, exist_ok=True)
        except Exception as e:
            self._log(f"Failed to create date folder {outdir}: {e}")
        base_name = ic.BASE_FILE_NAME

        for pos in range(1, npos + 1):
            if self._stop_requested:
                self._log("Collection aborted by emergency stop.")
                break

            # send SEQ so Arduino knows positions/pulses/distances/directions
            se_vals = [str(npos), str(npulses), self.vars["Dist X mm"].get(), self.vars["Dist Z mm"].get()]
            seq_cmd = "SEQ," + ",".join(se_vals + [self.dx.get(), self.dz.get()]) + "\n"
            try:
                self.conn.write(seq_cmd.encode())
                self._log(f"> {seq_cmd.strip()}")
            except Exception as e:
                self._log(f"Failed to send SEQ: {e}")
                return

            # allow time for stage to reach position (adjust if needed)
            time.sleep(1.0)

            for p in range(1, npulses + 1):
                if self._stop_requested:
                    self._log("Collection aborted by emergency stop.")
                    break

                # --- 1) Arm scope for single acquisition (skip if scope disabled) ---
                if self.scope_enabled.get():
                    try:
                        rm, scope, used = ic.discover_and_open(ic.DEFAULT_SCOPE_IP, ic.GLOBAL_TOUT)
                        try:
                            scope.write(":SINGle")
                            self._log("Scope armed (:SINGle)")
                        finally:
                            try: scope.close()
                            except Exception: pass
                            try: rm.close()
                            except Exception: pass
                    except Exception as e:
                        self._log("Failed to arm scope: " + str(e))
                        self._log("Aborting collection sequence.")
                        return
                else:
                    self._log("Oscilloscope disabled - skipping arming/collecting for this pulse")

                # small settle (if your hardware needs it)
                time.sleep(0.02)

                # flush any leftover input so handshake is clean
                try:
                    self.conn.reset_input_buffer()
                except Exception:
                    pass

                # --- 2) Tell Arduino it may start waiting for Q-switch (and open shutter after detection) ---
                try:
                    self.conn.write(b"NEXT\n")
                    self._log("> NEXT")
                except Exception as e:
                    self._log("Failed to send NEXT: " + str(e))
                    return

                # --- 3) Wait for Arduino to report the shot result ---
                line = self._wait_for_specific(["PULSE_DONE", "QTIMEOUT", "NEXT_TIMEOUT", "ERROR"], timeout=30.0)

                if self._stop_requested:
                    self._log("Interrupted after NEXT by emergency stop.")
                    break

                if line is None:
                    self._log(f"pos{pos} p{p}: timeout waiting for PULSE_DONE")
                    # Continue to next pulse
                    continue

                if line.startswith("PULSE_DONE"):
                    # Good — proceed to collect and save waveform (one file per pulse)
                    if self.scope_enabled.get():
                        try:
                            saved = ic.collect_waveform_and_save_once(
                                outdir=outdir,
                                first4=first4,
                                wavelength=wavelength,
                                pressure_str=pressure,
                                energy_mj=energy,
                                timescale_us=timescale,
                                posnum=pos,
                                pulsenum=p,
                                scope_ip=ic.DEFAULT_SCOPE_IP,
                                points=ic.DEFAULT_POINTS,
                                save_plots=False,
                                arm_after=False,
                                base_name=base_name
                            )
                            self._log(f"Saved: {saved}")
                        except Exception as e:
                            self._log(f"Error during collection for pos{pos} p{p}: {e}")
                            continue
                    else:
                        # scope disabled -> don't collect, just log
                        self._log(f"pos{pos} p{p}: pulse done (scope bypassed)")

                elif line.startswith("QTIMEOUT"):
                    self._log(f"pos{pos} p{p}: Arduino reported QTIMEOUT (no Q-switch event detected while shutter open).")
                    continue

                elif line.startswith("NEXT_TIMEOUT"):
                    self._log(f"pos{pos} p{p}: Arduino reported NEXT_TIMEOUT (it did not receive NEXT/permission in time).")
                    continue

                else:
                    self._log(f"pos{pos} p{p}: Unexpected Arduino response: {line}")
                    continue

                # small delay before next pulse (adjust as necessary)
                time.sleep(0.05)

            # after pulses at this position, move axes (use your MOV logic if needed)
            time.sleep(0.1)

        self._log("Collection sequence finished.")
        # save prefs at end of collection
        self.save_prefs()

    def emergency_stop(self):
        """Request an immediate stop. This will set a flag that causes collection to abort as soon as possible.
           It will also attempt to inform the Arduino and flush buffers. """
        self._log("*** EMERGENCY STOP requested ***")
        self._stop_requested = True
        # try to tell Arduino to stop (best-effort, Arduino may ignore if not programmed)
        try:
            if self.conn:
                try:
                    self.conn.write(b"STOP\n")
                    time.sleep(0.05)
                    self.conn.reset_input_buffer()
                    self.conn.reset_output_buffer()
                except Exception:
                    pass
        except Exception:
            pass
        # ensure any waiting loops exit
        self._waiting_for_line = False
        # update indicator to safe state (we keep shutter unknown until Arduino confirms)
        self.shutter_indicator.config(text="Shutter: UNKNOWN", bg="#CCCCCC")
        # save prefs to preserve user's entries
        self.save_prefs()

    def save_prefs(self):
        try:
            data = {
                'vars': {k: self.vars[k].get() for k in self.vars},
                'dx': self.dx.get(), 'dz': self.dz.get(),
                'prefix': self.prefix_entry.get(), 'wavelength': self.wavelength_entry.get(),
                'pressure': self.pressure_entry.get(), 'energy': self.energy_entry.get(),
                'timescale': self.timescale_entry.get(), 'manual_X': self.manual['X'].get(), 'manual_Z': self.manual['Z'].get(),
                'dir_X': getattr(self, 'dir_X').get(), 'dir_Z': getattr(self, 'dir_Z').get(),
                'scope_enabled': bool(self.scope_enabled.get())
            }
            with open(PREFS_FILE, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            # non-fatal, but log it
            self._log(f"Failed to save prefs: {e}")

    def load_prefs(self):
        if not os.path.exists(PREFS_FILE):
            return
        try:
            with open(PREFS_FILE, 'r') as f:
                data = json.load(f)
            for k, v in data.get('vars', {}).items():
                if k in self.vars:
                    self.vars[k].delete(0, 'end'); self.vars[k].insert(0, v)
            if 'dx' in data: self.dx.set(data.get('dx', 'F'))
            if 'dz' in data: self.dz.set(data.get('dz', 'F'))
            self.prefix_entry.delete(0,'end'); self.prefix_entry.insert(0, data.get('prefix',''))
            self.wavelength_entry.delete(0,'end'); self.wavelength_entry.insert(0, data.get('wavelength',''))
            self.pressure_entry.delete(0,'end'); self.pressure_entry.insert(0, data.get('pressure',''))
            self.energy_entry.delete(0,'end'); self.energy_entry.insert(0, data.get('energy',''))
            self.timescale_entry.delete(0,'end'); self.timescale_entry.insert(0, data.get('timescale',''))
            self.manual['X'].delete(0,'end'); self.manual['X'].insert(0, data.get('manual_X',''))
            self.manual['Z'].delete(0,'end'); self.manual['Z'].insert(0, data.get('manual_Z',''))
            getattr(self, 'dir_X').set(data.get('dir_X','F'))
            getattr(self, 'dir_Z').set(data.get('dir_Z','F'))
            self.scope_enabled.set(bool(data.get('scope_enabled', True)))
        except Exception as e:
            self._log(f"Failed to load prefs: {e}")

    def _on_close(self):
        # save prefs before exit
        self.save_prefs()
        try:
            if self.conn:
                try: self.conn.close()
                except Exception: pass
        finally:
            self.destroy()


if __name__=='__main__':
    App().mainloop()

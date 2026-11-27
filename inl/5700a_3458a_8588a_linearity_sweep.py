import argparse
import csv
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyvisa

GATEWAY = '192.168.0.5'
FLUKE_IP = '192.168.0.78'


def send_all(dmm, commands):
    for command in commands:
        dmm.write(command)


def setup_3458(rm, address, nread, nplc, period):
    dmm = rm.open_resource(f'TCPIP::{GATEWAY}::gpib0,{address}')
    dmm.timeout = 30000
    dmm.clear()
    commands = [
        'RESET', 'PRESET NORM', 'END ALWAYS', 'OFORMAT ASCII',
        'TRIG HOLD', 'DCV 10', 'FIXEDZ OFF', 'LFREQ 50',
        f'NPLC {nplc}', 'AZERO 1', f'TIMER {period:g}',
        f'NRDGS {nread},TIMER',
        'INBUF ON',
    ]
    send_all(dmm, commands)
    firmware = dmm.query('REV?').strip()
    return dmm, commands + ['TRIG SGL'], firmware


def setup_8588(rm, nread, nplc, period):
    dmm = rm.open_resource(f'TCPIP0::{FLUKE_IP}::3490::SOCKET')
    dmm.read_termination = '\n'
    dmm.write_termination = '\n'
    dmm.timeout = 30000
    firmware = dmm.query('*IDN?').strip().split(',')[-1]  # anonymizer
    commands = [
        'ABOR', '*CLS', '*RST', 'CONF:VOLT:DC 10',
        'ROUT:TERM FRONT', 'SENS:VOLT:DC:RANG:AUTO OFF',
        'SENS:VOLT:DC:IMP AUTO', 'SENS:VOLT:DC:RES MIN',
        'SENS:VOLT:DC:APER:MODE MAN', f'SENS:VOLT:DC:NPLC {nplc}',
        'CALC:AVER:STAT OFF', 'CALC:MATH:STAT OFF', 'FORM ASCII',
        'TRIG:RES', 'INIT:CONT OFF',
        'ARM:LAY2:SOUR IMM', 'ARM:LAY2:COUN 1',
        'ARM:LAY1:SOUR IMM', 'ARM:LAY1:COUN 1',
        'TRIG:DEL:AUTO OFF', 'TRIG:DEL 0',
        'TRIG:HOLD:AUTO ON', 'TRIG:SOUR TIM',
        f'TRIG:COUN {nread}', f'TRIG:TIM {period:g}',
    ]
    send_all(dmm, commands[:3])
    dmm.query('*OPC?')
    send_all(dmm, commands[3:])
    return dmm, commands + ['ABOR', 'INIT', 'FETC?'], firmware


def setup_5700(rm):
    dmm = rm.open_resource(f'TCPIP::{GATEWAY}::gpib0,1')
    dmm.timeout = 30000
    dmm.clear()
    commands = [
        '*RST', '*CLS', 'STBY', 'OUT 10 V, 0 Hz',
        'RANGELCK ON', 'OUT 0 V, 0 Hz', 'OPER',
    ]
    try:
        send_all(dmm, commands)
    except Exception:
        try:
            dmm.write('STBY')
        finally:
            dmm.close()
        raise
    return dmm, commands


def read_3458(dmm, count):
    dmm.write('TRIG SGL')
    return float(np.mean([float(dmm.read()) for _ in range(count)]))


def read_8588(dmm, count, window):
    dmm.write('ABOR')
    t0 = time.monotonic()
    dmm.write('INIT')
    time.sleep(max(0, window - (time.monotonic() - t0)))
    values = [float(s) for s in dmm.query('FETC?').split(',') if s.strip()]
    return float(np.mean(values))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--points', type=int, default=10)
    p.add_argument('--span', type=float, default=10)
    p.add_argument('--random_wobbble', type=float, default=1)
    p.add_argument('--nplc-3458', type=int, choices=[1, 10, 100], default=1)
    p.add_argument('--nplc-8588', type=int, choices=[1, 10, 100], default=100)
    p.add_argument('--window', type=int, default=5)
    p.add_argument('--soak', type=float, default=40)
    p.add_argument('--sweeps', type=int, default=1)
    p.add_argument('--addresses', type=int, nargs='+', default=[23, 22, 25])
    p.add_argument('--outdir', type=Path, default=Path('csv'))
    a = p.parse_args()
    period3458 = a.nplc_3458 * 0.05
    period8588 = a.nplc_8588 * 0.05
    n3458 = round(a.window / period3458)
    n8588 = round(a.window / period8588)
    a.outdir.mkdir(parents=True, exist_ok=True)
    prefix = '8588A_10V_INL_' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    rm = pyvisa.ResourceManager()
    meters = {}
    source = None
    try:
        settings = {'soak_s': a.soak, 'window_s': a.window,
                    '5700A': [], '3458A': [], '8588A': [], 'firmware': {}}
        for address in a.addresses:
            name = f'3458_{address}'
            meter, commands, revision = setup_3458(rm, address, n3458, a.nplc_3458, period3458)
            meters[name] = (meter, '3458')
            settings['3458A'] = commands
            settings['firmware'][name] = revision
        meter, commands, revision = setup_8588(rm, n8588, a.nplc_8588, period8588)
        meters['8588A'] = (meter, '8588')
        settings['8588A'] = commands
        settings['firmware']['8588A'] = revision
        source, settings['5700A'] = setup_5700(rm)
        (a.outdir / f'{prefix}.json').write_text(json.dumps(settings, indent=2) + '\n')

        names = list(meters)
        for s in range(a.sweeps):
            rows = []
            path = a.outdir / f'{prefix}_s{s+1}.csv'
            with path.open('x', newline='') as output:
                writer = csv.DictWriter(output, fieldnames=['time', 'Set_Voltage (V)'] + names)
                writer.writeheader()

                edges = np.linspace(-a.span, a.span, a.points + 1)
                test_points = np.random.uniform(edges[:-1], edges[1:])
                random.shuffle(test_points)
                print(f"Todays lucky numbers are:\n{test_points}")

                i = 0
                for v in test_points:
                    source.write(f'OUT {v:.7f} V, 0 Hz')
                    source.query('*OPC?')
                    time.sleep(a.soak)
                    row = {'time': datetime.now(timezone.utc).isoformat(),
                           'Set_Voltage (V)': float(v)}
                    order = names.copy()
                    random.shuffle(order)
                    for name in order:
                        instrument, kind = meters[name]
                        row[name] = (read_3458(instrument, n3458) if kind == '3458'
                                     else read_8588(instrument, n8588, a.window))
                    rows.append(row)
                    writer.writerow(row)
                    output.flush()
                    print(f'{i}/{a.points}  {v:+.4f} V  ' +
                          '  '.join(f'{n}={row[n]:+.9f}' for n in names), flush=True)
                    i += 1
            print('Saved:', path)
    finally:
        if source is not None:
            try:
                source.write('STBY')
            except Exception as exc:
                print('5700A stby:', exc)
        for meter, _ in meters.values():
            try:
                meter.close()
            except Exception:
                pass
        if source is not None:
            source.close()
        rm.close()


if __name__ == '__main__':
    main()

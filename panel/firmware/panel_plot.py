#!/usr/bin/env python

# Copyright 2015 Mikhail Afanasyev, mafanasyev@gmail.com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import optparse
import os
import serial
import struct
import subprocess
import sys
import time

class SerialReader(object):
    _HEADER = '\xFF\x36\xB0\xD4'

    def __init__(self, port, save_logs):
        self._dev = serial.serial_for_url(
            port, baudrate=57600, timeout=0.1)
        print >>sys.stderr, 'Opened port', port
        self._buff = ''

        self._logsave = None
        if save_logs:
            realname = time.strftime(save_logs, time.localtime())
            print >>sys.stderr, 'Saving logs to %r' % realname
            try:
                os.makedirs(os.path.dirname(realname))
            except OSError:
                pass
            self._logsave = open(realname, 'w')

    def _read_to_buff(self, min_len):
        """Read data until _buff contains at least _min_len bytes.
        return False on time, True if got enough data.
        """
        while len(self._buff) < min_len:
            rx = self._dev.read(min_len - len(self._buff))
            if rx == '':
                return False
            self._buff += rx
        return True

    def raw_read(self):
        """Read a packet, return a bytestring, or None on timeout."""
        while len(self._buff) > 4 and self._buff[:4] != self._HEADER:
            if self._buff[:-4] == '\x00':
                print >>sys.stderr, 'Saw 0x00 char -- probably hit marker'
            else:
                print >>sys.stderr, 'Discarding junk: %r' % self._buff[:-4]
            self._buff = self._buff[-4:]

        if len(self._buff) < 5:
            # Keep reading until we have 5 bytes starting with header
            self._read_to_buff(5)
            return None

        assert self._buff[:4] == self._HEADER
        total_len = 6 + ord(self._buff[4]) * 4
        if not self._read_to_buff(total_len):
            print >>sys.stderr, (
                'Warning: discarded incomplete packet (%d/%d bytes)' % (
                    len(self._buff), total_len))
            self._buff = ''
            return None

        result, self._buff = self._buff[:total_len], self._buff[total_len:]
        return result

    def read(self):
        raw = self.raw_read()
        if raw is None:
            return None
        # Assume version and length is valid

        # Verify checksum
        bytes_to_cs = struct.unpack('%dB' % (len(raw) - 1), raw[:-1])
        csum_real = sum(bytes_to_cs) & 0xFF
        csum_spec = ord(raw[-1])
        csum_error = None
        if csum_real != csum_spec:
            print >>sys.stderr, \
                'Discard packet with bad checksum: 0x%.2X != 0x%.2X' % (
                csum_real, csum_spec)
            return None

        # Start building result array.
        now = time.time()
        result = dict(
            time_num=now,
            time_str=time.strftime('%F %T', time.localtime(now))
            )

        # Parse header
        vrate, thresh, adc_offset, reserved = struct.unpack(
            'BBbB', raw[5:9])
        if (vrate & 0xD8) == 0:
            # Extract data
            data = tuple(
                x - adc_offset
                for x in struct.unpack('%db' % (len(raw) - 10), raw[9:-1]))

            triggerred = (vrate & (1<<5)) == 0
            divisor = 1 << max(2, vrate & 7)
            result.update(
                version=0,
                threshold=thresh,
                adc_offset=adc_offset,
                reserved=reserved,
                trigger_sample=(len(data) / 4 - 1) if triggerred else None,
                v_scale=1.1 / 128.0,   # reference voltage is 1.1 volts
                point_freq=8e6 / 13.5 / divisor,
                data=data,
                data_len=len(data),
                )
        else:
            assert False, 'Invalid firmware version %r' % vrate

        if self._logsave:
            stringified = json.dumps(result, sort_keys=True)
            print >>self._logsave, stringified
            self._logsave.flush()
        return result

class LogReader(object):
    def __init__(self, fn):
        if fn == '-':
            self._file = sys.stdin
        else:
            self._file = open(fn, 'r')

    def read(self):
        line = self._file.readline()
        if line == '':
            return None
        return json.loads(line)

class GnuPlotter(object):
    """Plot graphs using background gnuplot invocation.
    gnuplot has fewer features than matplotlib, but it works much better
    in a background
    """

    def __init__(self, persist=False):
        arg = []
        if persist:
            arg += ['-persist']
        self._persist = persist
        self._proc = subprocess.Popen(['gnuplot'] + arg,
                                      stdin=subprocess.PIPE)
        self._plots = 0
        print >>self._proc.stdin, 'set term wxt noraise title "panel_plot"'

    def poll(self):
        rv = self._proc.poll()
        assert rv is None, 'gnuplot terminated with code %r' % rv

    def plot(self, packet):
        self.poll()
        self._plots += 1
        self._generate_plot_commands(packet, self._proc.stdin)
        if self._plots == 1:
            # Raise window to foreground
            print >>self._proc.stdin, 'raise'

    def _generate_plot_commands(self, packet, fh):
        meta = dict(packet)
        if meta['trigger_sample'] is not None:
            meta['title'] = 'Trigger'
        else:
            meta['title'] = 'Idle'
            meta['trigger_sample'] = 0

        print >>fh, """
xtime(x)=(x - %(trigger_sample)d) / %(point_freq)f * 1000.0

set grid xtics ytics
set xlabel 'Time, milliseconds (freq %(point_freq).1fHz)'
set xrange [xtime(0):xtime(%(data_len)d + 1)]

yvolt(y) = y * %(v_scale)f

set yrange [-128:128]
set ylabel 'Input, ADC ticks (offset %(adc_offset)d)'

set y2range [yvolt(-128):yvolt(128)]
set y2label 'Input, Volts'
set y2tics

set title '%(title)s on %(time_str)s'
#unset label
#set label '%(time_str)s#(num)s' at graph 1, 0.03 right front

set arrow 1 from xtime(0),%(threshold)d \
            to xtime(%(data_len)d + 1),%(threshold)d nohead
set arrow 2 from xtime(0),-%(threshold)d \
            to xtime(%(data_len)d + 1),-%(threshold)d nohead

plot "-" using (xtime($1)):($2) with linespoints title '' pt 12
""" % meta
        for idx, val in enumerate(packet["data"]):
            print >>fh, idx, val
        print >>fh, "e"
        fh.flush()

    def close(self):
        if not self._persist:
            self._proc.terminate()

def main():
    parser = optparse.OptionParser(
        '%prog [options]')
    parser.add_option('-s', '--serial', metavar='/dev/tty...',
                      help='Read data from this serial port')
    parser.add_option('-r', '--read-log', metavar='FN',
                      help='Read data from this file')
    parser.add_option('-p', '--plot', action='store_true',
                      help='Plot graphs')
    parser.add_option('-w', '--save-logs', metavar='FN',
                      default='panel-logs/panel-%F-%H%M%S.json',
                      help='With -s, write logs to a specified file '
                      "(default '%default', empty string to disable)")
    opts, args = parser.parse_args()
    if args:
        parser.error('No positional arguments accepted')
    if opts.serial and opts.read_log:
        parser.error('Cannot read from serial and log simultaneously')

    reader = None
    if opts.serial:
        reader = SerialReader(opts.serial,
                              save_logs=opts.save_logs)
    elif opts.read_log:
        reader = LogReader(opts.read_log)
    else:
        parser.error('No data source')

    if opts.plot:
        plotter = GnuPlotter(persist=(not opts.serial))
    else:
        plotter = None

    try:
        t0 = None
        while True:
            if plotter: plotter.poll()
            pkt = reader.read()
            if pkt is None:
                if not opts.read_log:
                    # Idle on serial port
                    continue
                print 'File finished, exiting'
                time.sleep(1.0)
                break

            printable = dict(pkt)
            printable['data'] = '%d points (%d..%d)' % (
                len(pkt['data']), min(pkt['data']), max(pkt['data']))
            if pkt['trigger_sample'] is not None:
                printable['data_t'] = pkt['data'][pkt['trigger_sample'] - 2:
                                                      pkt['trigger_sample'] + 2]
            ts = printable.pop('time_num')
            if t0 is None:
                t0 = ts

            print '%.3f:' % (ts - t0), (
                ', '.join('%s=%s' % kv for kv in sorted(printable.iteritems())))

            if plotter: plotter.plot(pkt)
    finally:
        if plotter: plotter.close()

if __name__ == '__main__':
    main()

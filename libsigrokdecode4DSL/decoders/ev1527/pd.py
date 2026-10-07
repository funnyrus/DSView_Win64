#!/usr/bin/env python3

import sigrokdecode as srd

class Decoder(srd.Decoder):
    api_version = 3
    id = 'ev1527'
    name = 'EV1527'
    longname = 'EV1527 OOK Protocol'
    desc = 'EV1527 24-bit OOK remote control protocol with configurable timing.'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = []
    tags = ['Embedded/industrial']
    channels = (
        {'id': 'data', 'name': 'DATA', 'desc': 'Data line'},
    )
    optional_channels = ()
    options = (
        {'id': 'polarity', 'desc': 'Pulse polarity',
         'default': 'active-low', 'values': ('active-low', 'active-high')},
        {'id': 'sync_high', 'desc': 'Sync high pulse (μs)',
         'default': 280, 'min': 100, 'max': 1000},
        {'id': 'sync_low', 'desc': 'Sync low pulse (μs)',
         'default': 9330, 'min': 5000, 'max': 15000},
        {'id': 'bit_high', 'desc': 'Data bit high pulse (μs)',
         'default': 290, 'min': 100, 'max': 1000},
        {'id': 'bit0_low', 'desc': 'Logic 0 low pulse (μs)',
         'default': 910, 'min': 500, 'max': 2000},
        {'id': 'bit1_low', 'desc': 'Logic 1 low pulse (μs)',
         'default': 340, 'min': 200, 'max': 800},
        {'id': 'tolerance', 'desc': 'Timing tolerance (%)',
         'default': 25, 'min': 5, 'max': 50},
        {'id': 'show_decimal', 'desc': 'Show decimal values',
         'default': 'yes', 'values': ('yes', 'no')},
    )
    annotations = (
        ('bit', 'Bit'),
        ('sync', 'Sync'),
        ('word', 'Word'),
        ('address', 'Address'),
        ('command', 'Command'),
        ('warning', 'Warning'),
    )
    annotation_rows = (
        ('bits-row', 'Bits', (0,)),
        ('syncs-row', 'Syncs', (1,)),
        ('words-row', 'Words', (2,)),
        ('addrs-row', 'Addresses', (3,)),
        ('cmds-row', 'Commands', (4,)),
        ('warnings-row', 'Warnings', (5,)),
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.samplerate = None
        self.sync_high_samples = 0
        self.sync_low_samples = 0
        self.bit_high_samples = 0
        self.bit0_low_samples = 0
        self.bit1_low_samples = 0
        self.tolerance = 0.25
        self.state = 'WAIT_FOR_SYNC'
        self.bits = []
        self.ss_block = None
        self.es_block = None

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)

    def format_word(self, value, bits):
        """Format value with both hex and decimal representation"""
        hex_str = "0x{:0{}X}".format(value, bits // 4)
        if self.options['show_decimal'] == 'yes':
            return "{} ({})".format(hex_str, value)
        return hex_str

    def decode(self):
        if not self.samplerate:
            raise Exception("Cannot decode without samplerate.")

        # Convert user parameters from μs to samples
        self.sync_high_samples = int(self.samplerate * self.options['sync_high'] / 1e6)
        self.sync_low_samples = int(self.samplerate * self.options['sync_low'] / 1e6)
        self.bit_high_samples = int(self.samplerate * self.options['bit_high'] / 1e6)
        self.bit0_low_samples = int(self.samplerate * self.options['bit0_low'] / 1e6)
        self.bit1_low_samples = int(self.samplerate * self.options['bit1_low'] / 1e6)
        self.tolerance = self.options['tolerance'] / 100.0

        while True:
            # Wait for sync high pulse
            self.wait({0: 'h'})
            sync_high_start = self.samplenum
            self.wait({0: 'l'})
            sync_high_end = self.samplenum
            sync_high_width = sync_high_end - sync_high_start

            # Check sync high pulse
            if abs(sync_high_width - self.sync_high_samples) > self.sync_high_samples * self.tolerance:
                continue

            # Wait for sync low pulse
            sync_low_start = self.samplenum
            self.wait({0: 'h'})
            sync_low_end = self.samplenum
            sync_low_width = sync_low_end - sync_low_start

            # Check sync low pulse
            if abs(sync_low_width - self.sync_low_samples) > self.sync_low_samples * self.tolerance:
                continue

            # Valid sync found
            self.put(sync_high_start, sync_low_end, self.out_ann, [1, ['Sync', 'S']])

            # Decode 24 data bits
            self.bits = []
            self.ss_block = sync_high_start
            
            for _ in range(24):
                # Wait for bit high pulse
                self.wait({0: 'h'})
                bit_high_start = self.samplenum
                self.wait({0: 'l'})
                bit_high_end = self.samplenum
                bit_high_width = bit_high_end - bit_high_start

                # Wait for bit low pulse
                bit_low_start = self.samplenum
                self.wait({0: 'h'})
                bit_low_end = self.samplenum
                bit_low_width = bit_low_end - bit_low_start

                # Determine bit value
                if abs(bit_low_width - self.bit0_low_samples) <= self.bit0_low_samples * self.tolerance:
                    bit = 0
                elif abs(bit_low_width - self.bit1_low_samples) <= self.bit1_low_samples * self.tolerance:
                    bit = 1
                else:
                    self.put(bit_high_start, bit_low_end, self.out_ann, 
                            [5, ['Invalid bit width: {}μs'.format(int(bit_low_width*1e6/self.samplerate)), 'Inv']])
                    break

                self.bits.append(bit)
                self.put(bit_high_start, bit_low_end, self.out_ann, [0, [str(bit)]])

            # Process complete word
            if len(self.bits) == 24:
                word = 0
                for i, bit in enumerate(self.bits):
                    word |= bit << (23 - i)
                
                address = (word >> 8) & 0xFFFF
                command = word & 0xFF
                
                # 显示完整字（24位），包含16进制和十进制
                word_str = self.format_word(word, 24)
                self.put(self.ss_block, bit_low_end, self.out_ann, 
                        [2, ['Word: {}'.format(word_str), 'W:{}'.format(word_str)]])
                
                # 显示地址（16位），包含16进制和十进制
                addr_str = self.format_word(address, 16)
                self.put(self.ss_block, bit_low_end, self.out_ann, 
                        [3, ['Addr: {}'.format(addr_str), 'A:{}'.format(addr_str)]])
                
                # 显示命令（8位），包含16进制和十进制
                cmd_str = self.format_word(command, 8)
                self.put(self.ss_block, bit_low_end, self.out_ann, 
                        [4, ['Cmd: {}'.format(cmd_str), 'C:{}'.format(cmd_str)]])
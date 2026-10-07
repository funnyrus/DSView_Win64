##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2024 CC2500 SPI Protocol Decoder
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##

import sigrokdecode as srd

# CC2500 寄存器地址映射
registers = {
    0x00: 'IOCFG2', 0x01: 'IOCFG1', 0x02: 'IOCFG0', 0x03: 'FIFOTHR',
    0x04: 'SYNC1', 0x05: 'SYNC0', 0x06: 'PKTLEN', 0x07: 'PKTCTRL1',
    0x08: 'PKTCTRL0', 0x09: 'ADDR', 0x0A: 'CHANNR', 0x0B: 'FSCTRL1',
    0x0C: 'FSCTRL0', 0x0D: 'FREQ2', 0x0E: 'FREQ1', 0x0F: 'FREQ0',
    0x10: 'MDMCFG4', 0x11: 'MDMCFG3', 0x12: 'MDMCFG2', 0x13: 'MDMCFG1',
    0x14: 'MDMCFG0', 0x15: 'DEVIATN', 0x16: 'MCSM2', 0x17: 'MCSM1',
    0x18: 'MCSM0', 0x19: 'FOCCFG', 0x1A: 'BSCFG', 0x1B: 'AGCCTRL2',
    0x1C: 'AGCCTRL1', 0x1D: 'AGCCTRL0', 0x1E: 'WOREVT1', 0x1F: 'WOREVT0',
    0x20: 'WORCTRL', 0x21: 'FREND1', 0x22: 'FREND0', 0x23: 'FSCAL3',
    0x24: 'FSCAL2', 0x25: 'FSCAL1', 0x26: 'FSCAL0', 0x27: 'RCCTRL1',
    0x28: 'RCCTRL0', 0x29: 'FSTEST', 0x2A: 'PTEST', 0x2B: 'AGCTEST',
    0x2C: 'TEST2', 0x2D: 'TEST1', 0x2E: 'TEST0',
    # 状态寄存器
    0x30: 'PARTNUM', 0x31: 'VERSION', 0x32: 'FREQEST', 0x33: 'LQI',
    0x34: 'RSSI', 0x35: 'MARCSTATE', 0x36: 'WORTIME1', 0x37: 'WORTIME0',
    0x38: 'PKTSTATUS', 0x39: 'VCO_VC_DAC', 0x3A: 'TXBYTES', 0x3B: 'RXBYTES',
    0x3C: 'RCCTRL1_STATUS', 0x3D: 'RCCTRL0_STATUS',
    # PATABLE和FIFO访问
    0x3E: 'PATABLE',
    0x3F: 'FIFO',
}

# CC2500 命令字节
commands = {
    0x30: 'SRES',     # 复位芯片
    0x31: 'SFSTXON',  # 启用并校准频率合成器
    0x32: 'SXOFF',    # 关闭晶振
    0x33: 'SCAL',     # 校准频率合成器
    0x34: 'SRX',      # 启用RX
    0x35: 'STX',      # 启用TX
    0x36: 'SIDLE',    # 退出RX/TX
    0x38: 'SWOR',     # 启动自动RX轮询
    0x39: 'SPWD',     # 进入功耗降低模式
    0x3A: 'SFRX',     # 刷新RX FIFO
    0x3B: 'SFTX',     # 刷新TX FIFO
    0x3C: 'SWORRST',  # 重置实时时钟
    0x3D: 'SNOP',     # 无操作
}

class Decoder(srd.Decoder):
    api_version = 3
    id = 'cc2500'
    name = 'CC2500'
    longname = 'Texas Instruments CC2500'
    desc = 'CC2500 2.4GHz RF transceiver protocol decoder'
    license = 'gplv2+'
    inputs = ['spi']
    outputs = ['cc2500']
    tags = ['IC', 'Wireless', 'RF']
    annotations = (
        ('cmd', 'Command'),
        ('reg-read', 'Register Read'),
        ('reg-write', 'Register Write'),
        ('data', 'Data'),
        ('warning', 'Warning'),
        ('status', 'Status Byte'),
        ('frequency', 'Frequency Info'),
    )
    annotation_rows = (
        ('commands', 'Commands', (0,)),
        ('regs', 'Registers', (1, 2)),
        ('data', 'Data', (3,)),
        ('status', 'Status', (5,)),
        ('frequency', 'Frequency', (6,)),
        ('warnings', 'Warnings', (4,)),
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.ss_cmd, self.es_cmd = 0, 0
        self.mosi_bytes = []
        self.miso_bytes = []
        self.cmd_type = None
        self.reg_addr = None
        self.burst = False
        # 频率相关寄存器 - 使用持久化存储,不在每次传输时重置
        
    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)
        # 初始化频率寄存器存储
        self.freq_regs = {'FREQ2': None, 'FREQ1': None, 'FREQ0': None, 'CHANNR': None}
        self.freq_ss = None

    def putx(self, data):
        self.put(self.ss_cmd, self.es_cmd, self.out_ann, data)

    def decode_header(self, mosi):
        """解码头字节"""
        read_write = (mosi >> 7) & 0x01
        burst = (mosi >> 6) & 0x01
        addr = mosi & 0x3F
        
        self.burst = bool(burst)
        self.reg_addr = addr
        
        # 判断命令类型
        if addr >= 0x30 and addr <= 0x3D and not read_write:
            # 命令字节
            self.cmd_type = 'CMD'
            cmd_name = commands.get(addr, 'UNKNOWN')
            return f"CMD: {cmd_name} (0x{addr:02X})"
        else:
            # 寄存器访问
            reg_name = registers.get(addr, f"0x{addr:02X}")
            mode = "READ" if read_write else "WRITE"
            burst_str = " BURST" if burst else ""
            self.cmd_type = 'REG_READ' if read_write else 'REG_WRITE'
            return f"{mode}{burst_str}: {reg_name}"

    def decode_status(self, miso):
        """解码状态字节"""
        chip_rdy = (miso >> 7) & 0x01
        state = (miso >> 4) & 0x07
        fifo_bytes = miso & 0x0F
        
        states = {
            0: 'IDLE', 1: 'RX', 2: 'TX', 3: 'FSTXON',
            4: 'CALIBRATE', 5: 'SETTLING', 6: 'RXFIFO_OVERFLOW',
            7: 'TXFIFO_UNDERFLOW'
        }
        
        state_name = states.get(state, 'UNKNOWN')
        rdy = "RDY" if not chip_rdy else "NOT_RDY"
        
        return f"Status: {state_name} | {rdy} | FIFO:{fifo_bytes}"
    
    def calculate_frequency(self):
        """计算CC2500的工作频率"""
        if None in [self.freq_regs['FREQ2'], self.freq_regs['FREQ1'], self.freq_regs['FREQ0']]:
            return None
        
        # 组合24位频率字
        freq_word = (self.freq_regs['FREQ2'] << 16) | (self.freq_regs['FREQ1'] << 8) | self.freq_regs['FREQ0']
        
        # CC2500频率计算公式: F = (F_xosc / 2^16) * FREQ[23:0]
        # F_xosc = 26 MHz (CC2500标准晶振频率)
        f_xosc = 26e6  # 26 MHz
        base_freq = (f_xosc / 65536) * freq_word
        
        # 如果有信道号,计算实际频率
        # F_carrier = F_base + CHANNR * channel_spacing
        # channel_spacing通常为200kHz (0.2MHz), 但也取决于MDMCFG0寄存器
        if self.freq_regs['CHANNR'] is not None:
            channel_spacing = 0.2e6  # 默认200kHz
            actual_freq = base_freq + (self.freq_regs['CHANNR'] * channel_spacing)
            return base_freq / 1e6, actual_freq / 1e6, self.freq_regs['CHANNR']
        
        return base_freq / 1e6, None, None
    
    def update_freq_register(self, reg_name, value, ss, es):
        """更新频率寄存器并尝试计算频率"""
        if reg_name in self.freq_regs:
            self.freq_regs[reg_name] = value
            
            # 只在FREQ0或CHANNR更新时计算并显示频率
            if reg_name in ['FREQ0', 'CHANNR']:
                freq_result = self.calculate_frequency()
                if freq_result:
                    if freq_result[1] is not None:  # 有信道号
                        base_freq, actual_freq, channel = freq_result
                        freq_info = f"Base: {base_freq:.4f} MHz | CH{channel}: {actual_freq:.4f} MHz"
                    else:
                        base_freq = freq_result[0]
                        freq_info = f"Base Frequency: {base_freq:.4f} MHz"
                    
                    # 输出频率信息到当前数据字节的位置
                    self.put(ss, es, self.out_ann, [6, [freq_info]])

    def decode(self, ss, es, data):
        ptype, mosi, miso = data

        if ptype == 'CS-CHANGE':
            if miso == 0:  # CS拉低,传输开始
                self.reset()
                self.ss_cmd = ss
            else:  # CS拉高,传输结束
                self.es_cmd = es
                
        elif ptype == 'DATA':
            self.es_cmd = es
            if not self.mosi_bytes:  # 第一个字节是头字节
                self.ss_cmd = ss
                header_info = self.decode_header(mosi)
                
                # 输出命令/寄存器信息
                if self.cmd_type == 'CMD':
                    self.putx([0, [header_info]])
                elif self.cmd_type == 'REG_READ':
                    self.putx([1, [header_info]])
                elif self.cmd_type == 'REG_WRITE':
                    self.putx([2, [header_info]])
                
                # 输出状态字节
                if miso is not None:
                    status_info = self.decode_status(miso)
                    self.put(ss, es, self.out_ann, [5, [status_info]])
            else:
                # 数据字节
                if self.cmd_type in ['REG_READ', 'REG_WRITE']:
                    byte_idx = len(self.mosi_bytes) - 1
                    
                    if self.cmd_type == 'REG_WRITE':
                        data_str = f"Data: 0x{mosi:02X} ({mosi})"
                        data_value = mosi
                    else:
                        data_str = f"Data: 0x{miso:02X} ({miso})"
                        data_value = miso
                    
                    self.put(ss, es, self.out_ann, [3, [data_str]])
                    
                    # 检查是否为频率相关寄存器并更新
                    reg_name = registers.get(self.reg_addr, None)
                    if self.cmd_type == 'REG_WRITE' and reg_name in ['FREQ2', 'FREQ1', 'FREQ0', 'CHANNR']:
                        self.update_freq_register(reg_name, data_value, ss, es)
            
            self.mosi_bytes.append(mosi)
            self.miso_bytes.append(miso)
##
## PD-Link A/B serial link protocol decoder for DSView (DreamSourceLab)
##
## Protocol definition: XiaomiPPS2PD / User/pd_link.h  (USART1, 115200 8N1)
##
##   frame : 0x5A | CMD | LEN | payload[LEN] | XOR(CMD, LEN, payload...)
##   LEN   : 0 .. 56
##
##   CMD 0x01 CAPS   A->B : u8 fixed_n
##                          fixed_n * { u16le mv, u16le ma }
##                          u8 pps_n
##                          pps_n   * { u16le vmin_mv, u16le vmax_mv, u16le ma }
##   CMD 0x02 REQ    B->A : u8 is_pps, u16le mv, u16le ma
##   CMD 0x03 VSAFE  B->A : u8 reason (0 PPS keepalive timeout, 1 detach, 2 PD reset)
##   CMD 0x04 ACK    A->B : u8 status (0 FAIL, 1 OK), u16le mv
##   CMD 0x05 STATUS A->B : u16le vbus_mv, u16le contract_mv, u16le contract_ma,
##                          u8 flags, u8 reserved
##                          flags: b0 CAPS_VALID, b1 VGOOD, b2 PPS_CONTRACT
##
## Stack this decoder on a UART decoder ("1:UART", 115200 8N1, 8 data bits).
## The command byte uniquely identifies the direction (the two lines are
## unidirectional), so one input line is enough - probe TX of either chip.
##

import sigrokdecode as srd

FRAME_HEAD  = 0x5A
MAX_PAYLOAD = 56

CMD_CAPS   = 0x01
CMD_REQ    = 0x02
CMD_VSAFE  = 0x03
CMD_ACK    = 0x04
CMD_STATUS = 0x05

MAX_FIXED = 7
MAX_PPS   = 4

CMD_NAME = {
    CMD_CAPS:   'CAPS',
    CMD_REQ:    'REQ',
    CMD_VSAFE:  'VSAFE',
    CMD_ACK:    'ACK',
    CMD_STATUS: 'STATUS',
}

# Direction is implied by the command byte: A->B and B->A share no command ids.
CMD_DIR = {
    CMD_CAPS:   'AB',
    CMD_ACK:    'AB',
    CMD_STATUS: 'AB',
    CMD_REQ:    'BA',
    CMD_VSAFE:  'BA',
}

DIR_TXT = {
    'AB': ('A→B', 'A->B'),
    'BA': ('B→A', 'B->A'),
}
VSAFE_REASON = {
    0: ('PPS 保活超时 → 回 5V', 'PPS 保活超时', 'PPS timeout'),
    1: ('设备拔出 → 回 5V 并断开 VMOS', '设备拔出', 'detach'),
    2: ('PD 重启 (Hard/Soft Reset) → 回 5V', 'PD 重启', 'PD reset'),
}

ACK_STATUS = {
    0: ('失败 FAIL', 'FAIL'),
    1: ('成功 OK', 'OK'),
}

ST_CAPS_VALID = 0x01
ST_VGOOD      = 0x02
ST_PPS        = 0x04

ANN_A2B   = 0
ANN_B2A   = 1
ANN_FIELD = 2
ANN_WARN  = 3


def fmt_v(mv):
    return '%d.%02dV' % (mv // 1000, (mv % 1000) // 10)


def fmt_a(ma):
    return '%d.%02dA' % (ma // 1000, (ma % 1000) // 10)


class Decoder(srd.Decoder):
    api_version = 3
    id = 'pd_link'
    name = 'PD-Link A/B'
    longname = 'XiaomiPPS2PD A/B serial link'
    desc = 'A/B 双芯片串口链路 (帧头 0x5A, XOR 校验), 见 User/pd_link.h'
    license = 'gplv2+'
    inputs = ['uart']
    outputs = []
    tags = ['Embedded/industrial']

    annotations = (
        ('a2b-frame', 'A→B frame'),
        ('b2a-frame', 'B→A frame'),
        ('field', 'Field'),
        ('warning', 'Warning'),
    )
    annotation_rows = (
        ('row-a2b', 'A -> B', (ANN_A2B,)),
        ('row-b2a', 'B -> A', (ANN_B2A,)),
        ('row-fields', 'Fields', (ANN_FIELD,)),
        ('row-warnings', 'Warnings', (ANN_WARN,)),
    )
    options = (
        {'id': 'show_fields', 'desc': '逐字段注解', 'default': 'yes',
         'values': ('yes', 'no')},
        {'id': 'show_raw', 'desc': '附加 payload 原始 HEX', 'default': 'no',
         'values': ('yes', 'no')},
        {'id': 'show_timing', 'desc': '显示相邻帧间隔 Δt', 'default': 'yes',
         'values': ('yes', 'no')},
        {'id': 'uart_warnings', 'desc': '报告 UART 帧错误', 'default': 'yes',
         'values': ('yes', 'no')},
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.buf = []                # 未消费字节: [(value, ss, es), ...]
        self.samplerate = None
        self.last_ss = None

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value

    # ------------------------------------------------------------------ utils
    def _put(self, cls, ss, es, texts):
        self.put(ss, es, self.out_ann, [cls, texts])

    @staticmethod
    def _crc(cmd, payload):
        c = (cmd ^ (len(payload) & 0xFF)) & 0xFF
        for b in payload:
            c ^= b
        return c & 0xFF

    # ------------------------------------------------------------------ input
    def decode(self, ss, es, data):
        ptype, rxtx, pdata = data
        if ptype != 'FRAME':
            return

        # 1-uart emits ('FRAME', 0, (value, frame_valid)).
        if isinstance(pdata, (tuple, list)) and len(pdata) >= 2:
            val, valid = pdata[0], pdata[1]
        else:
            val, valid = pdata, True

        if not valid and self.options['uart_warnings'] == 'yes':
            self._put(ANN_WARN, ss, es,
                      ['UART 帧错误(起始/停止位), 该字节仍参与解析', 'UART 帧错误'])

        self.buf.append((int(val) & 0xFF, ss, es))
        self._process()

    def _process(self):
        """Consume complete, CRC-valid frames; resync byte-by-byte on garbage.

        校验失败的候选帧只丢弃 1 字节再重新找帧头: 这样即使某个杂散 0x5A 后跟了
        一个很大的 LEN, 也不会把后面所有真实帧永久卡住。同时报告校验错误,
        避免坏帧无声消失 (固件侧是整帧丢弃, 语义一致)。
        """
        buf = self.buf
        while True:
            if len(buf) < 3:
                return
            if buf[0][0] != FRAME_HEAD:
                buf.pop(0)
                continue
            ln = buf[2][0]
            if ln > MAX_PAYLOAD:
                buf.pop(0)               # 非法长度, 这个 0x5A 不是帧头
                continue
            total = 4 + ln
            if len(buf) < total:
                return                   # 等更多字节
            vals = [b[0] for b in buf[:total]]
            crc_calc = self._crc(vals[1], vals[3:3 + ln])
            if crc_calc != vals[3 + ln]:
                self._put(ANN_WARN, buf[0][1], buf[total - 1][2],
                          ['校验失败: 收到 0x%02X, 计算 0x%02X (候选帧 CMD 0x%02X, LEN %d)'
                           % (vals[3 + ln], crc_calc, vals[1], ln),
                           '校验失败 CMD 0x%02X' % vals[1]])
                buf.pop(0)               # 前进一字节重新找帧头
                continue
            frame = buf[:total]
            del buf[:total]
            self._emit(frame)

    # ----------------------------------------------------------------- output
    def _emit(self, frame):
        """输出一个已通过校验的完整帧。"""
        vals = [b[0] for b in frame]
        ss_head, es_crc = frame[0][1], frame[-1][2]
        cmd, ln = vals[1], vals[2]
        payload = vals[3:3 + ln]
        crc_rx = vals[3 + ln]

        name = CMD_NAME.get(cmd)
        dkey = CMD_DIR.get(cmd)
        detail, fields, warns = self._parse_payload(cmd, payload)

        # 相邻帧间隔: 便于观察 500ms 心跳 / 2s PPS 保活
        tinfo = ''
        if self.options['show_timing'] == 'yes' and self.samplerate and self.last_ss is not None:
            dt = (ss_head - self.last_ss) / float(self.samplerate)
            tinfo = '  Δ%.3fms' % (dt * 1000.0) if dt < 1.0 else '  Δ%.4fs' % dt
        self.last_ss = ss_head

        if name is None:
            # 方向无法从未知命令字推断, 归入 Fields 行, 只标注原始 payload
            cls = ANN_FIELD
            head = 'CMD 0x%02X 未知命令' % cmd
        else:
            cls = ANN_A2B if dkey == 'AB' else ANN_B2A
            head = '%s %s' % (name, DIR_TXT[dkey][0])

        self._put(cls, ss_head, es_crc, ['%s: %s%s' % (head, detail, tinfo), head, name or '?'])

        if self.options['show_fields'] == 'yes':
            self._put(ANN_FIELD, frame[0][1], frame[0][2], ['帧头 0x5A', '0x5A'])
            self._put(ANN_FIELD, frame[1][1], frame[1][2],
                      ['命令 CMD 0x%02X (%s)' % (cmd, name or '未知'), 'CMD %s' % (name or '?')])
            self._put(ANN_FIELD, frame[2][1], frame[2][2],
                      ['长度 LEN = %d' % ln, 'LEN %d' % ln])
            for texts, i, j in fields:
                self._put(ANN_FIELD, frame[3 + i][1], frame[3 + j][2], texts)
            self._put(ANN_FIELD, frame[-1][1], frame[-1][2],
                      ['校验 XOR: 正确 (0x%02X)' % crc_rx, '校验 OK'])

        for w in warns:
            self._put(ANN_WARN, ss_head, es_crc, [w, w])

    def _parse_payload(self, cmd, p):
        """返回 (摘要文本, [(注解文本列表, payload首偏移, payload末偏移)], [警告])。"""
        ln = len(p)
        fields, warns = [], []
        raw = ' '.join('%02X' % b for b in p)
        if len(raw) > 160:
            raw = raw[:160] + ' ...'

        def u16(off):
            return p[off] | (p[off + 1] << 8)

        # 解析失败/未知时: 摘要只显示原始 payload, 具体原因进 Warnings 行
        def bad(msg):
            warns.append(msg)
            return tail('raw[%s]' % raw) if raw else '(空 payload)'

        def tail(txt):
            if self.options['show_raw'] == 'yes' and raw:
                return txt + '  raw[%s]' % raw
            return txt

        # ---------------------------------------------------------- CAPS
        if cmd == CMD_CAPS:
            if ln < 2:
                return bad('CAPS payload 过短 (%d < 2)' % ln), fields, warns
            fn = p[0]
            if fn > MAX_FIXED:
                return bad('CAPS 固定档数量非法 (%d > %d)' % (fn, MAX_FIXED)), fields, warns
            if ln < 1 + fn * 4 + 1:
                return bad('CAPS 长度不足 (固定档 %d 需 >=%d, 实际 %d)'
                           % (fn, 1 + fn * 4 + 1, ln)), fields, warns

            fields.append((['固定档数量 = %d' % fn, '固定 %d' % fn], 0, 0))
            off = 1
            fx = []
            for k in range(fn):
                mv, ma = u16(off), u16(off + 2)
                fields.append((['固定档%d: %d mV / %d mA  (%s / %s)'
                                % (k + 1, mv, ma, fmt_v(mv), fmt_a(ma)),
                                '%s/%s' % (fmt_v(mv), fmt_a(ma))], off, off + 3))
                fx.append('%s/%s' % (fmt_v(mv), fmt_a(ma)))
                off += 4

            pn = p[off]
            fields.append((['PPS 档数量 = %d' % pn, 'PPS %d' % pn], off, off))
            off += 1
            if pn > MAX_PPS:
                return bad('CAPS PPS 档数量非法 (%d > %d)' % (pn, MAX_PPS)), fields, warns
            if ln < off + pn * 6:
                return bad('CAPS 长度不足 (PPS %d 需 >=%d, 实际 %d)'
                           % (pn, off + pn * 6, ln)), fields, warns

            pp = []
            for k in range(pn):
                vmin, vmax, ma = u16(off), u16(off + 2), u16(off + 4)
                fields.append((['PPS%d: %d~%d mV / %d mA  (%s~%s / %s)'
                                % (k + 1, vmin, vmax, ma,
                                   fmt_v(vmin), fmt_v(vmax), fmt_a(ma)),
                                '%s~%s/%s' % (fmt_v(vmin), fmt_v(vmax), fmt_a(ma))],
                               off, off + 5))
                pp.append('%s~%s/%s' % (fmt_v(vmin), fmt_v(vmax), fmt_a(ma)))
                off += 6

            if ln > off:
                warns.append('CAPS 末尾有 %d 字节多余数据' % (ln - off))

            detail = '固定档 %d [%s]  PPS %d [%s]' % (fn, ', '.join(fx) or '-',
                                                     pn, ', '.join(pp) or '-')
            return tail(detail), fields, warns

        # ----------------------------------------------------------- REQ
        if cmd == CMD_REQ:
            if ln < 5:
                return bad('REQ payload 过短 (%d < 5)' % ln), fields, warns
            is_pps, mv, ma = p[0], u16(1), u16(3)
            kind = 'PPS' if is_pps else '固定档'
            if ln > 5:
                warns.append('REQ 末尾有 %d 字节多余数据' % (ln - 5))
            fields.append((['请求类型: %s (is_pps=%d)' % (kind, is_pps), kind], 0, 0))
            fields.append((['请求电压: %d mV (%s)' % (mv, fmt_v(mv)), '%s' % fmt_v(mv)], 1, 2))
            fields.append((['请求电流: %d mA (%s)' % (ma, fmt_a(ma)), '%s' % fmt_a(ma)], 3, 4))
            return tail('%s请求 %s / %s' % (kind, fmt_v(mv), fmt_a(ma))), fields, warns

        # --------------------------------------------------------- VSAFE
        if cmd == CMD_VSAFE:
            if ln < 1:
                return bad('VSAFE payload 为空'), fields, warns
            r = p[0]
            long_t, short_t, en_t = VSAFE_REASON.get(
                r, ('未知原因 0x%02X' % r, '未知原因 0x%02X' % r, 'unknown'))
            if ln > 1:
                warns.append('VSAFE 末尾有 %d 字节多余数据' % (ln - 1))
            if r not in VSAFE_REASON:
                warns.append('VSAFE 原因码未知: 0x%02X' % r)
            fields.append((['原因 = %d  %s' % (r, long_t), '%s' % short_t], 0, 0))
            return tail('原因 %d: %s' % (r, long_t)), fields, warns

        # ----------------------------------------------------------- ACK
        if cmd == CMD_ACK:
            if ln < 3:
                return bad('ACK payload 过短 (%d < 3)' % ln), fields, warns
            st, mv = p[0], u16(1)
            long_t, short_t = ACK_STATUS.get(st, ('未知状态 0x%02X' % st, '未知 0x%02X' % st))
            if st not in ACK_STATUS:
                warns.append('ACK 状态码未知: 0x%02X' % st)
            if ln > 3:
                warns.append('ACK 末尾有 %d 字节多余数据' % (ln - 3))
            fields.append((['执行结果: %s' % long_t, short_t], 0, 0))
            fields.append((['实际电压: %d mV (%s)' % (mv, fmt_v(mv)), '%s' % fmt_v(mv)], 1, 2))
            return tail('%s, 电压 %s' % (short_t, fmt_v(mv))), fields, warns

        # -------------------------------------------------------- STATUS
        if cmd == CMD_STATUS:
            if ln < 7:
                return bad('STATUS payload 过短 (%d < 7)' % ln), fields, warns
            vbus, cmv, cma, flags = u16(0), u16(2), u16(4), p[6]
            fl = []
            if flags & ST_CAPS_VALID:
                fl.append('CAPS_VALID')
            if flags & ST_VGOOD:
                fl.append('VGOOD')
            if flags & ST_PPS:
                fl.append('PPS合同')
            if flags & ~(ST_CAPS_VALID | ST_VGOOD | ST_PPS):
                warns.append('STATUS 标志位含未知位: 0x%02X' % flags)
            if ln > 8:
                warns.append('STATUS 末尾有 %d 字节多余数据' % (ln - 8))

            fields.append((['VBUS 实测: %d mV (%s)' % (vbus, fmt_v(vbus)), '%s' % fmt_v(vbus)], 0, 1))
            fields.append((['合同电压: %d mV (%s)' % (cmv, fmt_v(cmv)), '%s' % fmt_v(cmv)], 2, 3))
            fields.append((['合同电流: %d mA (%s)' % (cma, fmt_a(cma)), '%s' % fmt_a(cma)], 4, 5))
            fields.append((['标志位 0x%02X: %s' % (flags, ' | '.join(fl) or '无'),
                            '%s' % ('|'.join(fl) or '无')], 6, 6))
            if ln >= 8:
                fields.append((['保留字节 = 0x%02X' % p[7], '保留 0x%02X' % p[7]], 7, 7))

            detail = 'VBUS %s  合同 %s / %s  [%s]' % (
                fmt_v(vbus), fmt_v(cmv), fmt_a(cma), ' | '.join(fl) or '无')
            return tail(detail), fields, warns

        # ------------------------------------------------------- unknown
        return bad('未知命令 0x%02X (len=%d)' % (cmd, ln)), fields, warns

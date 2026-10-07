import sigrokdecode as srd
import codecs
from collections import deque

class Decoder(srd.Decoder):
    api_version = 3
    id = 'uart_string'
    name = 'UART String'
    longname = 'UART String Decoder'
    desc = 'Decodes UART data into strings with Chinese support and segmentation'
    license = 'gplv2+'
    inputs = ['uart']
    outputs = ['uart_string']
    tags = ['Comms']
    
    # 定义注解类型
    annotations = (
        ('text', 'Decoded text'),
        ('text-line', 'Text line'),
        ('control-char', 'Control characters'),
        ('warning', 'Warnings'),
        ('segment', 'Segmentation markers'),
    )
    
    # 定义注解行
    annotation_rows = (
        ('texts', 'Text', (0,)),
        ('lines', 'Lines', (1,)),
        ('controls', 'Control', (2,)),
        ('warnings', 'Warnings', (3,)),
        ('segments', 'Segments', (4,)),
    )
    
    # 配置选项
    options = (
        {'id': 'encoding', 'desc': '字符编码', 'default': 'utf-8',
         'values': ('utf-8', 'gbk', 'ascii', 'latin-1')},
        {'id': 'timeout_ms', 'desc': '超时分段时间 (ms)', 'default': 10},
        {'id': 'segment_on_crlf', 'desc': '换行分段', 'default': 'yes',
         'values': ('yes', 'no')},
        {'id': 'segment_on_timeout', 'desc': '超时分段', 'default': 'yes',
         'values': ('yes', 'no')},
        {'id': 'show_control_chars', 'desc': '显示控制字符', 'default': 'no',
         'values': ('yes', 'no')},
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.byte_buffer = bytearray()
        self.sample_start = None
        self.sample_end = None
        self.decoder = None
        self.last_sample = 0
        self.active = False
        self.control_chars_buffer = bytearray()
        self.control_start_sample = None
        self.control_end_sample = None

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)
        # 根据配置的编码创建解码器
        self.decoder = codecs.getincrementaldecoder(self.options['encoding'])()
        # 计算超时样本数
        self.timeout_samples = int(self.options['timeout_ms'] * self.samplerate / 1000)

    def decode(self, startsample, endsample, data):
        ptype, rxtx, pdata = data
        
        # 只处理有效的数据帧
        if ptype != 'FRAME':
            return
            
        data_value, frame_valid = pdata
        if not frame_valid:
            self.put_warning(startsample, endsample, "Invalid frame")
            return
            
        # 提取字节数据
        byte_val = data_value & 0xFF
        
        # 检查字符间超时
        current_gap = startsample - self.last_sample
        timeout_occurred = (self.options['segment_on_timeout'] == 'yes' and 
                           self.active and current_gap > self.timeout_samples)
        
        # 检查控制字符（CR/LF）
        is_control_char = byte_val in [0x0A, 0x0D]  # LF, CR
        should_segment = False
        
        # 处理超时分段
        if timeout_occurred:
            should_segment = True
            self.put_segment_marker(self.last_sample, startsample, "Timeout")
        
        # 处理控制字符分段
        if is_control_char and self.options['segment_on_crlf'] == 'yes':
            should_segment = True
            control_name = "LF" if byte_val == 0x0A else "CR"
            self.put_control_char(startsample, endsample, control_name)
        
        # 如果需要分段，先处理当前缓冲区
        if should_segment:
            self.flush_buffer()
        
        # 处理控制字符显示
        if is_control_char:
            if self.options['show_control_chars'] == 'yes':
                self.handle_control_char(byte_val, startsample, endsample)
            # 控制字符不进入主缓冲区
            return
        
        # 添加到主缓冲区
        if not self.active:
            self.sample_start = startsample
            self.active = True
            
        self.byte_buffer.append(byte_val)
        self.sample_end = endsample
        self.last_sample = endsample

    def handle_control_char(self, byte_val, startsample, endsample):
        """单独处理控制字符"""
        control_name = "LF" if byte_val == 0x0A else "CR"
        self.put_control_char(startsample, endsample, control_name)

    def flush_buffer(self):
        """处理缓冲区中的数据并生成注解"""
        if not self.active or not self.byte_buffer:
            return
            
        try:
            # 尝试解码字节数据
            text = self.decoder.decode(self.byte_buffer)
            
            if text:
                # 输出文本注解
                self.put(self.sample_start, self.sample_end, self.out_ann, 
                        [0, [text]])
                # 输出行级注解（用于整行显示）
                self.put(self.sample_start, self.sample_end, self.out_ann,
                        [1, [f"Line: {text}"]])
        except UnicodeDecodeError as e:
            # 处理解码错误
            self.put_warning(self.sample_start, self.sample_end, 
                            f"Decode error: {str(e)}")
        finally:
            # 重置缓冲区
            self.byte_buffer.clear()
            self.active = False

    def put_control_char(self, startsample, endsample, char_name):
        """输出控制字符注解"""
        self.put(startsample, endsample, self.out_ann, 
                [2, [f"{char_name}", f"{char_name}"]])
        # 同时作为分段标记
        self.put_segment_marker(startsample, endsample, f"Segment: {char_name}")

    def put_segment_marker(self, startsample, endsample, message):
        """输出分段标记"""
        self.put(startsample, endsample, self.out_ann,
                [4, [message, "Segment", "Seg"]])

    def put_warning(self, startsample, endsample, message):
        """输出警告信息"""
        self.put(startsample, endsample, self.out_ann, [3, [message]])

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value

    def finish(self):
        """处理所有剩余数据"""
        self.flush_buffer()

# 包装器类
class UARTStringWrapper:
    def __init__(self):
        self.decoder = None
        self.samplerate = None
        
    def set_samplerate(self, samplerate):
        self.samplerate = samplerate
        if self.decoder:
            self.decoder.metadata(srd.SRD_CONF_SAMPLERATE, samplerate)
            
    def create_decoder(self, options):
        self.decoder = Decoder()
        self.decoder.options = options
        self.decoder.start()
        if self.samplerate:
            self.decoder.metadata(srd.SRD_CONF_SAMPLERATE, self.samplerate)
        return self.decoder
        
    def process_uart_data(self, startsample, endsample, data):
        if self.decoder:
            self.decoder.decode(startsample, endsample, data)
            
    def finish(self):
        if self.decoder:
            self.decoder.finish()

# 全局实例
wrapper = UARTStringWrapper()

# 以下函数将被逻辑分析仪调用
def set_samplerate(samplerate):
    wrapper.set_samplerate(samplerate)
    
def create_decoder(options):
    return wrapper.create_decoder(options)
    
def decode_frame(startsample, endsample, data):
    wrapper.process_uart_data(startsample, endsample, data)
    
def finish_decoding():
    wrapper.finish()
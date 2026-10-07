# myprotocol.py
import sigrokdecode as srd

class Decoder(srd.Decoder):
    api_version = 3
	##协议标识，必须唯一
    id = 'irgeli'
	##协议名字
    name = 'Ir_GeRee'
	##协议长名字
    longname = 'Ir GeRee Protocol Decoder'
    desc = 'A simple protocol decoder example.'
    license = 'GPLv2+'
    tags = ['IR']
	#输入数据源
    inputs = ['logic']
	#输出数据源
    outputs = ['irgeli']
    channels = (
        {'id': 'myprotocol', 'name': 'My Protocol', 'desc': 'My Protocol signal'},
    )
    options = (
        {'id': 'sample_rate', 'desc': 'Sample rate in Hz', 'default': 200000},
		{'id': 'tolerance', 'desc': '偏移us', 'default': 50},
    )
    annotations = (
        ('start', 'Start'),
        ('connect', 'Connect'),
        ('data', 'Data'),
        ('end', 'End'),
        ('bit0', 'Bit 0'),
        ('bit1', 'Bit 1'),
		('debug', 'Debug'),
    )
    annotation_rows = (
        ('symbols', 'Symbols', (0, 1, 3, 4, 5)),
		('lab2', 'row2', (6,)),
        ('lab3', 'data', (2,)),
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = 'IDLE'
        self.bits = []
    
    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)
        self.sample_rate = self.options['sample_rate']  # Use the provided sample rate
        self.tolerance = self.options['tolerance']  # Use the provided sample rate

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.sample_rate = value

    def to_microseconds(self, sample_number):
        if self.sample_rate:
            return (sample_number / self.sample_rate) * 1000000
        return 0

    def debug_output(self, ss, es, duration, message):
        # Output the duration as a debug annotation
        self.put(ss, es, self.out_ann, [6, ['{}: {:.2f} us'.format(message, duration) + 's: {:.2f} us'.format(ss) + 'e: {:.2f} us'.format(es)]])

# 起始码：9000us 低电平 + 4500us高电平；
# 连接码：646us低电平 + 20000us高电平；
# 结束码：646us低电平 + 高电平；
# 数据0：646us低电平 + 516us高电平；
# 数据1：646us低电平 + 1643us高电平；
        
    def decode(self):
        # Timing tolerance in microseconds
        tolerance = self.tolerance
        def is_timing(duration, target):
            if ((duration>=target-tolerance) and (duration<=target+tolerance)):
                return True
            return False
            #return target - tolerance <= duration <= target + tolerance
        lastpos=0
        while True:
        #循环查找起始头 下降9000 上升
            while True:
                #下降沿
                if self.wait([{0: 'f'}]):
                        ss = self.samplenum
                        #上升沿
                        if self.wait([{0: 'r'}]):
                            es = self.samplenum
                            if(es-ss==1):
                                #屏蔽干扰
                                if self.wait([{0: 'r'}]):
                                    es = self.samplenum
                            duration = self.to_microseconds(es - ss)
                            self.debug_output(ss, es, duration, 'Start Low')
                            #判断低电平
                            if is_timing(duration, 9000):
                                #下降沿
                                if self.wait([{0: 'f'}]):
                                    lastpos = self.samplenum
                                    if(lastpos - es==1):
                                        #屏蔽干扰
                                        if self.wait([{0: 'f'}]):
                                            lastpos = self.samplenum
                                    duration = self.to_microseconds(lastpos - es)
                                    self.debug_output(es, lastpos, duration, 'Start High')
                                    #判断高电平
                                    if is_timing(duration, 4500):
                                        self.put(ss, lastpos, self.out_ann, [0, ['起始码']])
                                        break
            #35数据位
            for i in range(0,35):
                ss=lastpos
                #上升沿
                if self.wait([{0: 'r'}]):
                    es = self.samplenum
                    if(es-ss==1):
                        #屏蔽干扰
                        if self.wait([{0: 'r'}]):
                            es = self.samplenum
                    duration = self.to_microseconds(es-ss)
                    self.debug_output(ss,es, duration, 'DL')
                    #低电平
                    if is_timing(duration, 646):
                        #下降沿
                        if self.wait([{0: 'f'}]):
                            lastpos = self.samplenum
                            if(lastpos-es==1):
                                #屏蔽干扰
                                if self.wait([{0: 'f'}]):
                                    lastpos = self.samplenum
                            duration = self.to_microseconds(lastpos - es)
                            self.debug_output(es,lastpos, duration, 'DH')
                            #高电平
                            if is_timing(duration, 516):
                                self.put(ss, lastpos, self.out_ann, [4, ['0']])
                            elif is_timing(duration, 1643):
                                self.put(ss, lastpos, self.out_ann, [5, ['1']])
                #解析数据
                #0-2模式 自动000 制冷100 除湿010 送风110 制热001
                if (i==2):
                    st=1
                #3开关
                elif(i==3):
                    st=1
                #4-5风速 自动00 一级10 二级 01 三级11
                elif(i==5):
                    st=1
                #6扫风
                elif(i==6):
                    st=1
                #7睡眠
                elif(i==7):
                    st=1
                #8-11温度 16 0000 17 1000 温度见下表
                elif(i==11):
                    st=1
                #12-14定时分钟 30min 100
                elif(i==14):
                    st=1
                #15定时
                elif(i==15):
                    st=1
                #16-19定时 1h 1000 2h 0100 3h 1100
                elif(i==19):
                    st=1
                #20加湿
                elif(i==20):
                    st=1
                #21灯光
                elif(i==21):
                    st=1
                #22负离子
                elif(i==22):
                    st=1
                #23节电
                elif(i==23):
                    st=1
                #24换气
                elif(i==24):
                    st=1

            #连接码
            ss=lastpos
            #上升沿
            if self.wait([{0: 'r'}]):
                es = self.samplenum
                if(es-ss==1):
                    #屏蔽干扰
                    if self.wait([{0: 'r'}]):
                        es = self.samplenum
                duration = self.to_microseconds(es-ss)
                self.debug_output(ss,es, duration, 'CL')
                #低电平
                if is_timing(duration, 646):
                    #下降沿
                    if self.wait([{0: 'f'}]):
                        lastpos = self.samplenum
                        if(lastpos-es==1):
                            #屏蔽干扰
                            if self.wait([{0: 'f'}]):
                                lastpos = self.samplenum
                        duration = self.to_microseconds(lastpos - es)
                        self.debug_output(es,lastpos, duration, 'CH')
                        #高电平
                        if is_timing(duration, 20000):
                            self.put(ss, lastpos, self.out_ann, [1, ['连接码']])
            #32数据位
            for i in range(0,32):
                ss=lastpos
                #上升沿
                if self.wait([{0: 'r'}]):
                    es = self.samplenum
                    if(es-ss==1):
                        #屏蔽干扰
                        if self.wait([{0: 'r'}]):
                            es = self.samplenum
                    duration = self.to_microseconds(es-ss)
                    self.debug_output(ss,es, duration, 'DL')
                    #低电平
                    if is_timing(duration, 646):
                        #下降沿
                        if self.wait([{0: 'f'}]):
                            lastpos = self.samplenum
                            if(lastpos-es==1):
                                #屏蔽干扰
                                if self.wait([{0: 'f'}]):
                                    lastpos = self.samplenum
                            duration = self.to_microseconds(lastpos - es)
                            self.debug_output(es,lastpos, duration, 'DH')
                            #高电平
                            if is_timing(duration, 516):
                                self.put(ss, lastpos, self.out_ann, [4, ['0']])
                            elif is_timing(duration, 1643):
                                self.put(ss, lastpos, self.out_ann, [5, ['1']])
                #解析数据
                #0上下扫风
                if (i==0):
                    st=1
                #3清除
                elif(i==3):
                    st=1
                #4左右扫风
                elif(i==4):
                    st=1
                #7清除
                elif(i==7):
                    st=1
                #8-9温度显示
                elif(i==9):
                    st=1
                #25清除
                elif(i==25):
                    st=1
                #26节能
                elif(i==26):
                    st=1
                #27清除
                elif(i==27):
                    st=1
                #28-31校验码 温度-18 +定时小时+开关x8
                elif(i==31):
                    st=1
            #结束码
            ss=lastpos
            #上升沿
            if self.wait([{0: 'r'}]):
                es = self.samplenum
                if(es-ss==1):
                    #屏蔽干扰
                    if self.wait([{0: 'r'}]):
                        es = self.samplenum
                duration = self.to_microseconds(es-ss)
                self.debug_output(ss,es, duration, 'EL')
                #低电平
                if is_timing(duration, 646):
                    self.put(ss, es, self.out_ann, [3, ['结束码']])



        #self.reset()

#16℃: 0000
#17℃: 1000
#18℃: 0100
#19℃: 1100
#20℃: 0010
#21℃: 1010
#22℃: 0110
#23℃: 1110
#24℃: 0001
#25℃: 1001
#26℃: 0101
#27℃: 1101
#28℃: 0011
#校验码 = (模式 – 1) + (温度– 16) + 5  + 左右扫风 + 换气 + 节能 - 开关  之后取二进制后四位，再逆序；
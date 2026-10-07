##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2021 QZ.Lee <lqz@wch.cn>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, see <http://www.gnu.org/licenses/>.
##

import sigrokdecode as srd


UI_MS = 1000000/1000.0
UI_US = 1000000/1000000.0

class SamplerateError(Exception):
	pass

class Decoder(srd.Decoder):
	api_version = 3
	id = 'fcp'
	name = '0 FCP'
	longname = 'FCP AFC SCP'
	desc = 'fcp class porotcol analize'
	license = 'gplv2+'
	inputs = ['logic']
	outputs = []
	tags = ['Charging']
	channels = (
		{'id': 'data', 'name': 'Data', 'desc': 'Data line'},
	)
	annotations = (
		('ping', 'Ping'),
		('sync', 'SYNC'),
		('bit', 'BIT'),
		('byte', 'BYTE'),
		('msg', 'Message'),
		('warning', 'Warning'),
	)
	annotation_rows = (
		 ('msg', 'Message', (4,5,)),
		 ('data', 'Data', (0,1,3,)),
		 ('symbol', 'Symbol', (2,)),	# ping,ack,sync,0,1
	)
	binary = (
		('raw', 'RAW file'),
	)

	def __init__(self):
		self.reset()

	def reset(self):
		self.samplerate = None
		self.ResetVar()

	def metadata(self, key, value):
		if key == srd.SRD_CONF_SAMPLERATE:
			self.samplerate = value
			
			self.maxgap = self.us2samples(800 * UI_US)	   
			self.rst_max = self.us2samples(20000 * UI_US)		  
			self.rst_min = self.us2samples(12000 * UI_US)	   
			self.ping_max = self.us2samples(3000 * UI_US)	   
			self.ping_min = self.us2samples(2000 * UI_US)	
			self.sync_max = self.us2samples(48 * UI_US)	 
			self.sync_min = self.us2samples(32 * UI_US)	   
			self.data_max = self.us2samples(1728 * UI_US)	 
			self.data_min = self.us2samples(128 * UI_US)		   
			
	def us2samples(self, us):
		return int(us * self.samplerate / 1000000)	   

	def start(self):
		self.out_ann = self.register(srd.OUTPUT_ANN)
		self.out_binary = self.register(srd.OUTPUT_BINARY)
		self.out_average = \
			self.register(srd.OUTPUT_META,
						  meta=(float, 'Average', 'PWM base (cycle) frequency'))


	def ResetVar(self):
		self.start_samplenum = 0
		self.stop_samplenum = 0
		self.ResetComm()
	
	
	
	
	def ResetComm(self):
		self.newflag = 1
		self.idxMaster = 0
		self.idxSlave = 0
		self.bufMaster = []
		self.bufSlave = []
		self.commseq = 0
		
		
	
	def putx(self, s0, s1, data):
		self.put(s0, s1, self.out_ann, data)	

	def decode(self):
		if not self.samplerate:
			raise SamplerateError('Cannot decode without samplerate.')


		while True:

			#错误时来此处进行复位 

			while True:
				
				self.wait({0: 'r'})
				self.start_samplenum = self.samplenum
				
				if ( self.start_samplenum - self.stop_samplenum ) > self.maxgap or self.commseq == 7:
					if self.commseq < 7 and self.commseq > 2 :
						self.putx(self.commstart, self.stop_samplenum, [5, ['BAD COMM']]) 
					self.ResetComm()
					self.commstart = self.start_samplenum
				else :
					self.newflag = 0
				
				self.wait({0: 'f'})
				self.stop_samplenum = self.samplenum
				delta = self.stop_samplenum - self.start_samplenum
				
#				self.putx(self.start_samplenum, self.stop_samplenum, [2, ['!']])
						
				if delta > self.rst_max:		# ERROR
					break
					
				elif delta > self.rst_min and delta < self.rst_max :		# rst
					self.putx(self.start_samplenum, self.stop_samplenum, [3, ['RESET']]) 
					break
					
				elif delta > self.ping_min and delta < self.ping_max :		# Ping/ACK
					self.commseq += 1
					if self.newflag == 1 :
						self.putx(self.start_samplenum, self.stop_samplenum, [0, ['Ping']]) 
					else :
						self.putx(self.start_samplenum, self.stop_samplenum, [0, ['ACK']]) 	
						if self.commseq == 7 :
							
							tmpstr = 'T['
							for i in range ( self.idxMaster ):
								tmpstr += ' %02X' % self.bufMaster[i]
							tmpstr += ' ] R['	
							for i in range ( self.idxSlave ):
								tmpstr += ' %02X' % self.bufSlave[i]
							tmpstr += ' ]'	
							
							self.putx(self.commstart, self.samplenum, [4, [tmpstr]]) 
					


				elif delta > self.sync_min and delta < self.sync_max :		# sync
					
					while True:
						
						while True:				# Wait for SYNC 
							
							self.wait([{0: 'e'}, {'skip': self.sync_max}])
							
							if (self.matched & (0b1 << 1)):
								break
								
						self.putx(self.start_samplenum, self.samplenum - self.sync_max, [1, ['S']])
						
						self.start_samplenum = self.samplenum - self.sync_max			#数据范围需减去一个syncMAX
						
						DataCnt = 0
						DataByte = 0
						while DataCnt < 8 :		# Recv DATA
							if DataCnt == 0 :
								self.wait({'skip': self.us2samples(80 * UI_US) - self.sync_max })
							else :
								self.wait({'skip': self.us2samples(160 * UI_US) })		
									
							DataByte <<= 1
							DataCnt += 1
							self.wait([{0: 'l'}, {0: 'h'}])
							if (self.matched & (0b1 << 1)):
								DataByte += 1
								self.putx(self.samplenum - self.sync_min, self.samplenum + self.sync_min, [2, ['1']])
							else :
								self.putx(self.samplenum-self.sync_min, self.samplenum+self.sync_min, [2, ['0']])
						
						
						self.wait({'skip': self.us2samples(160 * UI_US) })
						self.wait([{0: 'e'}, {'skip': self.us2samples(160 * UI_US) }])
						if (self.matched & (0b1 << 0)):			# 有沿则为数据 
							self.putx(self.start_samplenum, self.samplenum, [3, ['0x%02X' % DataByte]]) 
							self.start_samplenum = self.samplenum
							if self.commseq == 2 :
								self.bufMaster.append(DataByte)
								self.idxMaster += 1
							elif self.commseq == 4 :
								self.bufSlave.append(DataByte)
								self.idxSlave += 1
						else :
							self.wait([{'skip': self.ping_max },{0: 'f'}])
							if (self.matched & (0b1 << 1)):	
								self.putx(self.start_samplenum, self.samplenum, [0, ['END']]) 
								self.commseq += 1
							self.stop_samplenum = self.samplenum
							
							break
			
			
			
			
			

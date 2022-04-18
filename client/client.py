import threading
from enum import Enum
from utils import VMState, ClientState
import logging
import socket
import time
import sys
import libvirt
import argparse
import numpy as np
import random

# Work provided to servers are to store the license plate
# number safely and also cross verify the hash
def generate_random_license_plate():
    license_plate_initials = ["AN", "AP", "AR", "AS", 
                    "BH", "BR", "CH", "CG", "DD", 
                    "DL", "GA", "GJ", "HR", "HP", 
                    "JK", "JH", "KA", "KL", "LA", 
                    "LD", "MP", "MH", "MN", "ML", 
                    "MZ", "NL", "OD", "PY", "PB", 
                    "RJ", "SK", "TN", "TS", "TR", 
                    "UP", "UK", "WB"]
    # taking template as 2 origin chars 2 digits 2 chars 4 digits
    string1 = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    string2 = "1234567890"
    len1 = len(string1)
    len2 = len(string2)
    origin_length = 
    license_number = ""
    
    # Get origin of license plate
    index = random.randint(0, origin_length - 1)
    license_number += license_plate_initials[index]

    license_number += "-"
    for i in range(2):
        index = random.randint(0, len2 - 1)
        license_number += string2[index]
    license_number += "-"
    for i in range(2):
        index = random.randint(0, len1 - 1)
        license_number += string1[index]
    license_number += "-"
    for i in range(4):
        index = random.randint(0, len2 - 1)
        license_number += string2[index]
    return license_number

# VM Definition
# VM contains the following attributes
# Name: Unique Name for the VM
# IP: IP address for communication over network
# State: State of the VM
# -	IDLE
# -	BUSY
# -	BOOTING
# -	SHUT_OFF
# -	ERROR
class VM(object):
	def __init__(self, name=None, ip=None, state=None):
		self.name = name
		self.ip = ip
		self.state = state

accept_vm_port = 5000
server_port = 5001
receive_result_port = 5002
cpu_thresh = 80.0
delta = 1
servers = {}
servers_lock = threading.Lock()
running = True

client_state = ClientState.CONSTANT
cpu_load = 0.0		

class AcceptVM(threading.Thread):
	def __init__(self, port):
		threading.Thread.__init__(self)
		self.port = port
		
	def run(self):
		global servers, servers_lock, client_state, running
		skt = socket.socket()
		skt.bind(('0.0.0.0', self.port))
		skt.listen(10)
		while running:
			conn, address = skt.accept()
			ip = str(address[0])
			name = conn.recv(1024).decode()
			logging.info(f"New VM {name} accepted at ip {ip}")
			servers_lock.acquire()
			vm = VM(name=name, ip=ip, state=VMState.IDLE)
			servers[ip] = vm
			servers_lock.release()
			conn.close()
			if client_state == ClientState.BOOTING:
				client_state = ClientState.RELAX
				logging.debug('Client state: relaxed')
		skt.close()


class ReceiveResult(threading.Thread):
	def __init__(self, port):
		threading.Thread.__init__(self)
		self.port = port
		
	def run(self):
		global servers, servers_lock, running
		skt = socket.socket()
		skt.bind(('0.0.0.0', self.port))
		skt.listen(10)
		while running:
			conn, address = skt.accept()
			ip = str(address[0])
			data = conn.recv(1024).decode()
			logging.info(f"Received stored hashed response {data} from {servers[ip].name}")
			servers_lock.acquire()
			servers[ip].state = VMState.IDLE
			servers_lock.release()
			conn.close()
		skt.close()


class SendWork(threading.Thread):
	def __init__(self, server_port, delta):
		threading.Thread.__init__(self)
		self.server_port = server_port
		self.delta = delta
		
	def run(self):
		global servers, servers_lock, running
		i = 1
		while running:
			word = generate_random_license_plate()
			done = False
			logging.debug('Searching for idle server...')
			while not done:
				servers_lock.acquire()
				for ip, vm in servers.items():
					if vm.state == VMState.IDLE:
						server_ip = ip
						port = self.server_port
						skt = socket.socket()
						skt.settimeout(3)
						try:
							skt.connect((server_ip, port))
						except socket.error as exc:
							logging.error(f'Socket error for VM {vm.name}: {exc}')
							vm.state = VMState.ERROR
							continue
						skt.send(word.encode())
						servers[ip].state = VMState.BUSY
						logging.info(f"Sent License Number {word} to {vm.name} VM.")
						skt.close()
						done = True
						break
				servers_lock.release()
			time.sleep(self.delta)
			i+=1


def get_ip_address(dom):
	ip = dom.interfaceAddresses(0)['vnet0']['addrs'][0]['addr']


class VMManager(threading.Thread):

	def __init__(self, cpu_thresh, url):
		threading.Thread.__init__(self)
		self.cpu_thresh = cpu_thresh
		self.url = url
	

	def get_cpu_time(self, vm):
		conn = libvirt.open(self.url)
		dom = conn.lookupByName(vm.name)
		dom_state = dom.info()[0]
		if dom_state != 1:
			logging.error(f'VM {vm.name} not running')
			return -1
		else:
			cpu_stats = dom.getCPUStats(True)
			conn.close()
			return cpu_stats[0]['cpu_time']


	def boot_new_server(self):
		conn = libvirt.open(self.url)
		doms = conn.listDefinedDomains()
		if doms == []:
			logging.debug('No defined domains')
		else:
			dom = conn.lookupByName(doms[0])
			dom.create()
			logging.info(f'Powered on domain {doms[0]}')
		
		conn.close()


	def shut_one_server(self):
		global servers, servers_lock
		conn = libvirt.open(self.url)
		servers_lock.acquire()
		for ip, vm in servers.items():
			if vm.state == VMState.IDLE:
				dom = conn.lookupByName(vm.name)
				r = dom.shutdown()
				if r == 0:
					logging.info(f'Shutdown domain {vm.name}')
					servers[ip].state = VMState.SHUT_OFF
				else:
					logging.error(f'Error in shutdown domain {dom.name}')
				servers_lock.release()
				return
		servers_lock.release()
		logging.error(f'No idle domain to shut')

	def shut_all_servers(self):
		global servers, servers_lock
		conn = libvirt.open(self.url)
		servers_lock.acquire()
		for ip, vm in servers.items():
			dom = conn.lookupByName(vm.name)
			dom_state = dom.info()[0]
			r = -1
			if dom_state != 5:
				r = dom.shutdown()
			if r == 0:
				logging.info(f'Shutdown domain {vm.name}')
				servers[ip].state = VMState.SHUT_OFF
			else:
				logging.error(f'Error in shutdown domain {dom.name}')
		servers_lock.release()

	def run(self):
		global servers, servers_lock, client_state, running
		while running:
			start_cpu_time = {}
			start_time = time.time()
			servers_lock.acquire()
			running_vm = 0
			for ip, vm in servers.items():
				if vm.state == VMState.BUSY or vm.state == VMState.IDLE:
					cpu_time = self.get_cpu_time(vm)
					if cpu_time == -1:
						vm.state = VMState.ERROR
						continue
					start_cpu_time[ip] = cpu_time
				if not (vm.state == VMState.SHUT_OFF or vm.state == VMState.ERROR):
					running_vm += 1
			servers_lock.release()
			if running_vm == 0 and client_state == ClientState.CONSTANT:
				logging.info(f'No running VM, starting new server...')
				self.boot_new_server()
				client_state = ClientState.BOOTING
				logging.debug('Client state: booting')
			time.sleep(30)
			loads = []
			servers_lock.acquire()
			for ip, vm in servers.items():
				if vm.state == VMState.BUSY or vm.state == VMState.IDLE:
					if ip not in start_cpu_time:
						start_cpu_time[ip] = 0
					cpu_time = self.get_cpu_time(vm)
					if cpu_time == -1:
						vm.state = VMState.ERROR
						continue
					vm_load = (cpu_time - start_cpu_time[ip]) / (time.time() - start_time) / 1e9 * 100
					# logging.debug(f'{cpu_time}, {start_cpu_time[ip]}, {(time.time() - t)} {vm_load}')
					logging.debug(f'CPU load for {vm.name}: {int(vm_load)}%')
					loads.append(vm_load)
			servers_lock.release()
			average_load = 0
			if loads:
				average_load = np.mean(loads)

			logging.info(f'average CPU load: {int(average_load)}%')
			if average_load > self.cpu_thresh and client_state == ClientState.CONSTANT:
				logging.info(f'Detected high load, starting new server...')
				self.boot_new_server()
				client_state = ClientState.BOOTING
				logging.debug('Client state: booting')
			else:
				n = len(loads)
				left = (self.cpu_thresh - average_load) * n
				if n > 1 and left > cpu_thresh and client_state == ClientState.CONSTANT:
					logging.info('Detected low load')
					self.shut_one_server()
					client_state = ClientState.RELAX
					logging.debug('Client state: relax')

			if client_state == ClientState.RELAX:
				client_state = ClientState.CONSTANT
				logging.debug('Client state: constant')

		self.shut_all_servers()


if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument("--url", type=str, default='qemu:///system')
	parser.add_argument("--loglevel", type=str, default='info')

	args = parser.parse_args()
	numeric_level = getattr(logging, args.loglevel.upper(), None)
	if not isinstance(numeric_level, int):
		raise ValueError('Invalid log level: %s' % loglevel)
	logging.basicConfig(level=numeric_level, format='%(asctime)s - %(levelname)s: %(message)s', filename='log',
                        filemode='a')
	accept_vm = AcceptVM(accept_vm_port)
	worker = SendWork(server_port, delta)
	receive_result = ReceiveResult(receive_result_port)
	vm_manager = VMManager(cpu_thresh, url=args.url)

	worker.start()
	accept_vm.start()
	receive_result.start()
	vm_manager.start()

	logging.info("Hello User. Work will be given to the VMs.")

	while True:
		inp = input()
		if inp == 'terminate':
			logging.info('Command received to terminate the process.')
			running = False
			vm_manager.join()
			print('Press the standard Ctrl-C to exit completely.')
			worker.join()
			accept_vm.join()
			receive_result.join()
			break

		delta = float(inp)
		worker.delta = delta

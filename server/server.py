import socket
import uuid
import hashlib
import threading
import logging
import time


client_ip = '192.168.122.1'
client_port = 5002
server_ready_port = 5000
server_port = 5001
 
def hash_license_number(license_number):
    # uuid is used to generate a random number
    salt = uuid.uuid4().hex
    return hashlib.sha256(salt.encode() + license_number.encode()).hexdigest() + ':' + salt
    
def check_license_number(hashed_license_number, user_license_number):
    license_number, salt = hashed_license_number.split(':')
    return license_number == hashlib.sha256(salt.encode() + user_license_number.encode()).hexdigest()

def verify_license_numbers_n_times(license_number, n = 1):
    h = hash_license_number(license_number)
    l = []
    while(n):
        l.append(check_license_number(h, license_number))
    return h

def calculate_collision_string(data):
    h = lambda x: hashlib.sha256(x.encode('utf-8')).hexdigest()
    x =  h(data)
    i=0
    while True:
        if h(str(i))[:6] == x[:6]:
            break
        i+=1
    return str(i)


def loop_for_t(data, t=5):
    import time
    start = time.time()
    i=0
    while True:
        i+=1
        if (time.time() - start) > t:
            break
    return str(i)


def notify_client(client_ip, server_ready_port):
    skt = socket.socket()
    skt.connect((client_ip, server_ready_port))
    skt.send(socket.gethostname().encode())
    logging.info(f'Notified client of the new server')
    skt.close()


class Worker(threading.Thread):

    def __init__(self, receive_port, client_ip, client_port, function, function2):
        threading.Thread.__init__(self)
        self.receive_port = receive_port
        self.client_ip = client_ip
        self.client_port = client_port
        self.function = function
        self.function2 = function2

    def send_result(self, result):
        send_socket = socket.socket()
        send_socket.connect((self.client_ip, self.client_port))
        send_socket.send(result.encode())
        logging.info(f'Sent to client ip {client_ip} result {result}')
        send_socket.close()

    def run(self):
        receive_socket = socket.socket()
        receive_socket.bind(('0.0.0.0', self.receive_port))
        receive_socket.listen(1)
        while True:
            logging.info(f'Listening for work')
            conn, address = receive_socket.accept()
            ip = address[0]
            work = conn.recv(1024).decode()
            logging.info(f'Received License Number {work} from {ip} address.')
            conn.close()
            # result = self.function(work, 1)
            h = hash_license_number(work)
            result = self.function2(work)
            self.send_result(h)
        receive_socket.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s', filename='log',
                        filemode='a')
    worker = Worker(server_port, client_ip, client_port, verify_license_numbers_n_times, calculate_collision_string)
    # worker = Worker(server_port, client_ip, client_port, calculate_collision_string)

    worker.start()
    time.sleep(1)
    notify_client(client_ip, server_ready_port)

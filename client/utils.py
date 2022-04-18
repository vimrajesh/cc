from enum import Enum

class VMState(Enum):
	IDLE = 1
	BUSY = 2
	BOOTING = 3
	SHUT_OFF = 4
	ERROR = 5


class ClientState(Enum):
	CONSTANT = 1
	RELAX = 2
	BOOTING = 3
	ERROR = 4
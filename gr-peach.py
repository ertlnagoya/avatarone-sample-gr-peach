
import os
import signal
from sys import exit
from time import time, sleep 
import re
import subprocess

from avatar.emulators.s2e import init_s2e_emulator
from avatar.system import System
from avatar.targets.gdbserver_target import *
from avatar.targets.openocd_jig import *
from avatar.targets.openocd_target import *

# BIN_FILE = "../project/gr-peach/build/gr-peach.bin"
BIN_FILE = "./gr-peach.bin"

"""
/* Linker script to configure memory regions. */
MEMORY
{
  ROM   (rx)  : ORIGIN = 0x00000000, LENGTH = 0x02000000
  BOOT_LOADER (rx) : ORIGIN = 0x18000000, LENGTH = 0x00004000 
  SFLASH (rx) : ORIGIN = 0x18004000, LENGTH = 0x07FFC000 
  L_TTB (rw)  : ORIGIN = 0x20000000, LENGTH = 0x00004000 
  RAM (rwx) : ORIGIN = 0x20020000, LENGTH = 0x00700000
  RAM_NC (rwx) : ORIGIN = 0x20900000, LENGTH = 0x00100000
}
"""

configuration = {
    'output_directory': '/tmp/avatar_gr-peach/',
    'configuration_directory': os.getcwd(),
    "s2e": {
        "emulator_gdb_path": "/home/avatar/projects/gdb-build/gdb/gdb",
        "emulator_gdb_additional_arguments": ["--data-directory=/home/avatar/projects/gdb-build/gdb/data-directory/"],
        's2e_binary': '/home/avatar/projects/s2e-build/qemu-release/arm-s2e-softmmu/qemu-system-arm',
        # 's2e_binary': '/home/avatar/workspace/new-s2e/s2e-build/qemu-release/arm-s2e-softmmu/qemu-system-arm',
        "klee": {
        },
        "plugins": {
            "BaseInstructions": {},
            "Initializer": {},
            "MemoryInterceptor": "",
            "RemoteMemory": {
                "verbose": True,
                "writeBack": True, # FixMe: NOT WORKS
                "listen_address": "localhost:9998",
                "ranges":  {
                    "peripherals": {
                        "address": 0xe8000000,
                        "size": 0xffffffff - 0xe8000000,
                        "access": ["read", "write", "execute", "io", "memory", "concrete_value", "concrete_address"]
                    },                   
                    "flash": {
                        "address": 0x20000000, # SRAM (mbed DigitalOut instance comes hore) $sp = 0x20720000, 20020c34
                        "size": 0x20a00000 - 0x20000000,
                        "access": ["read", "write", "execute", "io", "memory", "concrete_value", "concrete_address"]
                    },    
                },
            },
        },
        "include" : [],
    },

    "qemu_configuration": {
        "gdbserver": False, # 'True' not works
        "halt_processor_on_startup": True,
        "trace_instructions": True,
        "trace_microops": False,
        "append": ["-serial", "tcp::8888,server,nowait","-S"]
    },

    'machine_configuration': {
        'architecture': 'arm',
        'cpu_model': 'cortex-a9',
        'entry_address': 0x18005d78, # Reset_Handler
        "memory_map": [
            {
                "size": 0x08000000,
                "name": "rom",
                "file": BIN_FILE,
                "map": [
                    {"address": 0x18000000, # Flash Memory (ROM) (BIN_FILE goes here)
                     "type": "code",
                     "permissions": "rwx"}
                ]
            },
        ],
    },

    "avatar_configuration": {
        "target_gdb_address": "tcp:localhost:3333",
        "target_gdb_additional_arguments": ["--data-directory=/home/avatar/projects/gdb-build/gdb/data-directory/"],
        "target_gdb_path": "/home/avatar/projects/gdb-build/gdb/gdb",
    },
    'openocd_configuration': {
        'config_file': 'renesas_gr-peach.cfg'
    }
    }


def get_symbol_addr(file_name, symbol):
    out = subprocess.check_output("readelf -s %s" % file_name, shell=True, universal_newlines=True)
    for line in out.split('\n'):
        line += "$"
        if line.find(" " + symbol + "$") >= 0:
            # print(line)
            # m = re.match(r'\d+: ([0-9a-f]+)\s+\d+ (\w+)\D+\d+ ([^\s@]+)', line)
            m = re.match(r'^\s+\d+\: ([0-9a-f]+)\s', line)
            return int("0x" + m.group(1), 16)
    return -1 # ERROR

# gdb-mi: -data-list-register-names
"""
{'sp_svc': 102, 'lr_fiq': 99, 'sp_und': 106, 'r9_fiq': 94, 'sp_usr': 91, 'r11': 11, 'lr_irq': 101, 'lr': 14, 'spsr_irq': 109, 'r10': 10, 'sp_abt': 104, 'sp_irq': 100, 'lr_usr': 92, 'r11_fiq': 96, 'r6': 6, 'lr_mon': 114, 'r4': 4, 'r9': 9, 'cpsr': 25, 'r12_fiq': 97, 'sp_mon': 113, 'lr_abt': 105, 'r2': 2, 'r0': 0, 'r1': 1, 'r12': 12, 'pc': 15, 'sp': 13, 'spsr_und': 112, 'r5': 5, 'sp_fiq': 98, 'spsr_svc': 110, 'spsr_abt': 111, 'r10_fiq': 95, 'r3': 3, 'r7': 7, 'r8': 8, 'spsr_mon': 115, 'r8_fiq': 93, 'lr_svc': 103, 'spsr_fiq': 108, 'lr_und': 107}
"""
REGISTERS = [
    'r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'r8', 'r9', 'r10', 'r11',
    'r12', 'sp', 'lr', 'pc', 'cpsr'
]

def get_regs(debuggable):
    regs = []
    print("==== [dump registers] ====")
    for r in REGISTERS:
        print("$%s = %#x" % (r, debuggable.get_register(r)))
        regs.append(debuggable.get_register(r))
    print("==========================")
    return regs

def set_regs(debuggable, regs):
    assert(len(regs) == len(REGISTERS))
    for i in range(len(regs)):
        # print("%s <= %#x" % (REGISTERS[i], regs[i]))
        debuggable.set_register(REGISTERS[i], regs[i])

def main():

    if not os.path.exists(BIN_FILE):
        print("[!] BIN_FILE = %s is not exists!" % BIN_FILE)
        exit()

    elf_file = BIN_FILE.replace(r".bin", r".elf")

    main_addr = get_symbol_addr(elf_file, "main")
    timeout_addr = get_symbol_addr(elf_file, "_Z3finv") 
    if timeout_addr < 0:
        print("[!] timout_addr not set. using __libc_fini_array")
        timeout_addr = get_symbol_addr(elf_file, "__libc_fini_array")
    print("[*] main = %#x, timeout = %#x" % (main_addr, timeout_addr))

    print("[*] Starting the GR-PEACH demo")


    print("[+] Resetting target via openocd")
    hwmon = OpenocdJig(configuration)
    cmd = OpenocdTarget(hwmon.get_telnet_jigsock())
    cmd.raw_cmd("reset halt")


    print("[+] Initilializing avatar")
    ava = System(configuration, init_s2e_emulator, init_gdbserver_target)
    ava.init()
    ava.start()
    t = ava.get_target()
    e = ava.get_emulator()


    print("[+] Running initilization procedures on the target")
    print("first break point = %#x" % main_addr)
    main_bkt = t.set_breakpoint(main_addr)
    t.cont()
    main_bkt.wait()

    print("[+] Target arrived at main(). Transferring state to the emulator")
    set_regs(e, get_regs(t))
    print("emulator pc = %#x" % e.get_register('pc'))
    e.set_register('sp', 0x114514)
    print("emulator sp = %#x" % e.get_register('sp'))
    get_regs(e)

    print("[+] Continuing execution in the emulator!")
    print("final break point = %#x" % timeout_addr)
    e_end_bp = e.set_breakpoint(timeout_addr)
    start = time.time()

    e.cont()

    e_end_bp.wait()
    duration = time.time() - start

    #Further analyses code goes here
    print("[+] analysis phase")
    print("elapsed time = %f sec" % duration)

    e.stop() # important
    t.stop() # important

if __name__ == '__main__':
    main()
    print("[*] finished")
    os.system("kill " + str(os.getpid()))
    exit()

# Fluke 8588A — serial console access and temporary Linux root shell

It's running Ångström Linux v2018.06, kernel 4.9.78-ltsi-altera with U-Boot 2016.11on an Altera Cyclone V SoC FPGA.


## 1. serial console hardware

On the rear digital board there is a 10-pin header labelled "Console" next to a MAX3232 transceiver. PXL_20261116_185742718.jpeg shows the pinout.

## 2. Open a serial terminal

RS232 levels, 115200 baud 8n1 and no flow control

## 3. Interrupt U-Boot

Start the instrument with picocom already connected, mash keys at "Hit any key to stop autoboot"

Inspect the boot setup and find:

```text
bootcmd=run qspifpga; bridge enable; run rotate_init; run qspiload; run qspiboot
qspirootpartition=ubi.mtd=4
qspiroot=ubi0:root-fs
qspirootfstype=ubifs
mem=1040384k
loadaddr=0x1000000
fdtaddr=100
```
The stock `qspiboot` command resets `bootargs`, so setting `init=/bin/sh` and then executing `run bootcmd` will **not** preserve the change. We execute its preparatory steps manually instead.

## 4. Load the normal FPGA, kernel and device tree into RAM

Enter these commands:

```text
run qspifpga
bridge enable
run rotate_init
run qspiload
```

The two QSPI flash reads should report `Read: OK`:

```text
device 0 offset 0x800000, size 0x600000
SF: 6291456 bytes @ 0x800000 Read: OK
...
device 0 offset 0x200000, size 0x600000
SF: 6291456 bytes @ 0x200000 Read: OK
device 0 offset 0x110000, size 0xffff
SF: 65535 bytes @ 0x110000 Read: OK
```

## 5. Set a temporary kernel command line

Add a sneaky little `init=/bin/sh`:

```text
setenv bootargs 'quiet loglevel=3 console=ttyS0,115200 ubi.mtd=4 root=ubi0:root-fs rw rootfstype=ubifs vt.global_cursor_default=0 vt.cur_default=1 coherent_pool=256K mem=1040384k isolcpus=1 init=/bin/sh'
printenv bootargs
```
The rw is dangerous. Don't delete or modify anything without understanding or you'll brick your expensive DMM.

## 6. Boot to a root shell

Run:

```text
bootz ${loadaddr} - ${fdtaddr}
```

## 7. Enjoy a deep dive in the filesystem

```sh
id
ls -la /
ls -la /home/Vanquish/
ls -la /home/Vanquish/nv/
```

The nv directory contained:

```text
Passwords.txt
REMSETUP.yml
SERNUM.yml
Vanquish.ini
```

/home/Vanquish/nv/Passwords.txt is probably what you are here for.


## 8. Return to normal

Power cycle it






user pw=123456
factory pw=7913058
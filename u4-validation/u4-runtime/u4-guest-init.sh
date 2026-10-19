#!/bin/bash
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
exec </dev/console >/dev/console 2>&1
mkdir -p /dev/pts /tmp /run /results /mnt /sys/kernel/config
mount -t devpts devpts /dev/pts
mount -t tmpfs -o size=256m tmpfs /tmp
mount -t tmpfs tmpfs /run
mount -t tmpfs -o size=128m tmpfs /mnt
hostname u4-disposable
ip link set lo up
# Host side of the loopback connection; the checks load the target modules
# the way middleware does.
modprobe nvme_tcp
python3 /u4/u4_renderer_checks.py 2>&1 | tee /results/checks.log
status=${PIPESTATUS[0]}
dmesg > /results/dmesg.log
cat /results/dmesg.log
printf 'U4_GUEST_EXIT=%s\n' "$status"
# Export small text evidence over the serial console without enabling guest networking.
tar -C /results -czf /tmp/u4-results.tgz .
echo U4_ARTIFACT_BEGIN
base64 -w 76 /tmp/u4-results.tgz
echo U4_ARTIFACT_END
sync
/bin/busybox poweroff -f

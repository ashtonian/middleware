#!/bin/bash
# Boot the disposable U4 guest: the qualified U3 production kernel with either its
# own (supported) or the base (unsupported) nvmet modules, driven by middleware's
# unmodified NVMe renderer. No network interface, drives or host devices.
set -euo pipefail
expect=${1:?supported or unsupported}
case "$expect" in supported|unsupported) ;; *) exit 2 ;; esac
u4=/work/u4
root="$u4/guest-$expect"
results="$u4/results/$expect"
release=6.18.55-production+truenas
image_deb=$(find /work -maxdepth 1 -type f -name 'linux-image-truenas-production-amd64_*.deb' -print -quit)
test -n "$image_deb"

rm -rf "$root" "$results"
mkdir -p "$results"
# Ubuntu 22.04 userspace from the U3 guest, without its kernel, modules or U3 tooling.
cp -a /work/guest-root "$root"
rm -rf "$root/boot" "$root/usr/lib/modules" "$root/u3" "$root/results" "$root/init"
dpkg-deb -x "$image_deb" "$root"
# Raw package extraction replaces Ubuntu's /lib symlink; restore usr-merge.
if [ ! -L "$root/lib" ]; then
    cp -a "$root/lib/." "$root/usr/lib/"
    rm -r "$root/lib"
    ln -s usr/lib "$root/lib"
fi
target="$root/usr/lib/modules/$release/kernel/drivers/nvme/target"
if [ "$expect" = unsupported ]; then
    install -m 644 "$u4/base-nvme/target/nvmet.ko" "$u4/base-nvme/target/nvmet-tcp.ko" "$target/"
fi
sha256sum "$image_deb" "$root/boot/vmlinuz-$release" "$target/nvmet.ko" "$target/nvmet-tcp.ko" > "$results/inputs.sha256"

python3 - "$root" "$release" <<'PY'
from pathlib import Path
import subprocess
import sys

root, release = Path(sys.argv[1]), sys.argv[2]
modules = root / 'usr/lib/modules' / release
subprocess.run(['depmod', '-b', str(root), release], check=True)
keep = set()
for name in ['nvmet', 'nvmet_tcp', 'nvme_tcp']:
    output = subprocess.check_output(['modprobe', '-d', str(root), '-S', release, '--show-depends', name], text=True)
    keep.update(Path(line.split()[1]) for line in output.splitlines() if line.startswith('insmod '))
# modprobe reports paths through the /lib symlink.
keep = {path.resolve() for path in keep}
assert keep and all(path.is_file() and path.is_relative_to(modules.resolve()) for path in keep), keep
for path in modules.rglob('*.ko*'):
    if path.resolve() not in keep:
        path.unlink()
subprocess.run(['depmod', '-b', str(root), release], check=True)
print('Guest module closure:', sorted(p.name for p in keep))
PY

mkdir -p "$root/u4" "$root/results" "$root/dev"
cp -a "$u4/mw" "$root/u4/mw"
cp "$u4/u4_renderer_checks.py" "$root/u4/"
cp "$u4/u4-guest-init.sh" "$root/init"
chmod 755 "$root/init"
[ -c "$root/dev/console" ] || { rm -f "$root/dev/console"; mknod "$root/dev/console" c 5 1; }
[ -c "$root/dev/null" ] || { rm -f "$root/dev/null"; mknod "$root/dev/null" c 1 3; }
(cd "$root/u4" && find mw u4_renderer_checks.py -type f -exec sha256sum {} + | sort -k2) > "$results/guest-files.sha256"
(cd "$root" && find . -print0 | cpio --null -o --format=newc 2> "$results/cpio.log" | gzip -1) > "$results/initramfs.gz"
sha256sum "$results/initramfs.gz" >> "$results/inputs.sha256"

set +e
timeout --signal=TERM --kill-after=15 2400 qemu-system-x86_64 \
    -machine q35,accel=tcg -cpu max -smp 2 -m 3072 \
    -nodefaults -display none -monitor none \
    -serial "file:$results/console.log" -no-reboot \
    -kernel "$root/boot/vmlinuz-$release" \
    -initrd "$results/initramfs.gz" \
    -append "console=ttyS0 edd=off loglevel=6 panic=1 rdinit=/init u4_disposable=1 u4_expect=$expect" \
    -nic none > "$results/qemu.log" 2>&1
status=$?
set -e
printf '%s\n' "$status" > "$results/qemu.exit"
grep 'U4_GUEST_EXIT=' "$results/console.log" || true
test "$status" -eq 0
python3 "$u4/extract-u4-results.py" "$results/console.log" "$results/guest"

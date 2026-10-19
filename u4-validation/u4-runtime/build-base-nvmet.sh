#!/bin/bash
# Build the TrueNAS base (pre-U3) nvmet modules against the qualified production
# build tree. U3 changes only drivers/nvme/target, so the production kernel with
# these modules behaves as the base kernel for the NVMe target.
set -euo pipefail
tree=/work/package-production
out=/work/u4/base-nvme
rm -rf "$out"
mkdir -p "$out"
# Sources only; the host directory is needed for relative includes.
tar -C "$tree/drivers/nvme" -cf - --exclude='*.o' --exclude='*.ko' --exclude='*.mod' \
    --exclude='*.mod.c' --exclude='.*.cmd' --exclude='modules.order' . | tar -C "$out" -xf -
(cd /work/u4/candidate-src && sha256sum -c --quiet /work/u4/candidate-src.sha256)
(cd "$tree/drivers/nvme/target" && sha256sum -c --quiet /work/u4/candidate-src.sha256)
cp /work/u4/base-src/* "$out/target/"
(cd "$out/target" && sha256sum -c --quiet /work/u4/base-src.sha256)
export ARCH=x86_64 CROSS_COMPILE=x86_64-linux-gnu- EXTRAVERSION=-production
make -C "$tree" M="$out/target" -j6 modules > /work/u4/base-nvmet-build.log 2>&1
for module in nvmet nvmet-tcp nvmet-rdma; do
    # Packaged modules are signed by modules_install; sign these the same way.
    "$tree/scripts/sign-file" sha256 "$tree/certs/signing_key.pem" "$tree/certs/signing_key.x509" \
        "$out/target/$module.ko"
    modinfo -F vermagic "$out/target/$module.ko"
    modinfo -F signer "$out/target/$module.ko"
done
sha256sum "$out/target/nvmet.ko" "$out/target/nvmet-tcp.ko" "$out/target/nvmet-rdma.ko"

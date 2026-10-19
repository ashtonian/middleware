# U4 renderer guest checks

These scripts run middleware's unmodified kernel NVMe renderer
(`middlewared/utils/nvmet/kernel.py`) against real nvmet configfs. They use the
disposable QEMU guest from [the U3 runtime lab](../runtime/README.md) and keep
its boundaries: the lane's builder container and private volume, TCG emulation,
no guest network interface, no drives, and no host devices. The only NVMe
backend is a 64 MiB file on guest tmpfs. `u4_renderer_checks.py` refuses to run
without `u4_disposable=1` on the kernel command line, or if the guest has any
block device.

This is a renderer and kernel integration check. It is not a TrueNAS appliance
test: the middleware daemon, datastore, CRUD validation, `etc.generate` and HA
peers are not running. The render contexts mirror what `etc.generate('nvmet')`
gathers for a non-HA system and for HA node A with ANA enabled.

## What runs

| Guest | Kernel | Checks |
| --- | --- | --- |
| `supported` | Qualified U3 production package `6.18.55-production+truenas` (`9d9d9d7`) | Limit written before link; Identify MDTS and host `max_hw_sectors_kb`; 1 MiB direct I/O; unchanged re-render on an enabled port; kernel refusal of a changed limit on an enabled port; disable/change/enable to 1 MiB and to `null`; ANA-derived port `5001` |
| `unsupported` | Same kernel image with `nvmet`/`nvmet-tcp` rebuilt from TrueNAS base `e43b652` | `null` ports render and serve without `param_mdts`; a non-null limit raises `EOPNOTSUPP` before its port is linked, other ports keep serving; clearing the limit links the port |

U3 changes only `drivers/nvme/target`, the `nvmet` and `nvmet-tcp` modules. For
the target driver, the production kernel with base modules is the base kernel.
`build-base-nvmet.sh` verifies the build tree's seven target files against the
candidate and the replacements against base. It builds with the tree's
configuration and `Module.symvers`, then signs with the tree's build key, as
`modules_install` does for packaged modules.

The guest runs Python 3.10 from the U3 Ubuntu 22.04 userspace; middleware ships
Python 3.13. The renderer files come unmodified from the U4 commit. Two modules
are stubbed because their real imports need appliance packages:
`service_exception.CallError`, which the renderer only constructs, and
`plugins/zfs_/utils.zvol_name_to_path`, which FILE namespaces never call.
Empty files replace the package `__init__` modules.

## Reproduce

1. On the host, run `MIDDLEWARE_REPO=<middleware clone> KERNEL_REPO=<linux clone>
   stage-u4-inputs.sh`. Set `MIDDLEWARE_COMMIT` for a later U4 head and
   `U4_CONTAINER` for another builder. The script exports exact Git objects
   into the builder's `/work/u4`.
2. In the builder: `bash /work/u4/build-base-nvmet.sh`.
3. In the builder: `bash /work/u4/boot-u4.sh supported`, then
   `bash /work/u4/boot-u4.sh unsupported`. Each one rebuilds its guest root from
   `/work/guest-root` and the production image package. It records input hashes
   and returns success only after the guest's complete PASS report is decoded
   into `/work/u4/results/<guest>/guest`.

Recorded results and their manifest are in `../results/u4-port-mdts/`.

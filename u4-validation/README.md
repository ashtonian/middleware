# U4 validation evidence

This branch holds reproducers and logs for
[`work/u4-port-transfer-limit`](https://github.com/ashtonian/middleware/tree/work/u4-port-transfer-limit)
at `bd9a462e8a1f6b7d854e284ecce37a9cd6c7df1e`. That head has two commits. The
first adds `nvmet.port.max_data_transfer_size`. The second leaves only a port
whose limit the kernel cannot apply without subsystems, and raises an alert
naming it. The evidence is not part of the proposed middleware change.

| Path | Contents |
| --- | --- |
| [`results/u4-port-mdts/summary.json`](results/u4-port-mdts/summary.json) | Manifest: base and candidate SHAs, CI image digest, results, scenario mapping, NOT RUN items and file hashes |
| `results/u4-port-mdts/*.log` | New unit tests, negative control against `master` sources, full `middlewared/pytest` run, docs changelog tests, ruff and the alembic upgrade/downgrade replay |
| [`u4-runtime/`](u4-runtime/README.md) | Guest harness that drives middleware's unmodified kernel NVMe renderer against real nvmet configfs |
| `results/u4-port-mdts/runtime/` | Guest results on the U3 production kernel with candidate (11/11) and with base (10/10) `nvmet` modules |

The unit runs used `ghcr.io/truenas/middleware:master` under emulated amd64.
The 16 failures in the full suite (3203 passed) are `ENOSYS` from `openat2`/`renameat2` in
modules this change does not touch. The guest runs use the U3-qualified kernel
from [truenas/linux#373](https://github.com/truenas/linux/pull/373); its package
evidence is
[here](https://github.com/ashtonian/linux/tree/f5098048f7ca7d3fb672478b1b301aa368756509/u3-validation).
TrueNAS appliance integration tests, HA failover, restart and configuration
import/export have not been run.

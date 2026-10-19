#!/usr/bin/env python3
"""Drive the U4 middleware NVMe renderer against real nvmet configfs in the disposable guest."""
import errno
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

sys.path.insert(0, '/u4/mw')
from middlewared.utils.nvmet import kernel  # noqa: E402  (unmodified candidate file)

ROOT = Path('/sys/kernel/config/nvmet')
RESULTS = Path('/results')
NS_FILE = Path('/mnt/u4/ns1.img')
NS_BYTES = 64 * 1024 * 1024
IO_BYTES = 1024 * 1024
BASENQN = 'nqn.2011-06.com.truenas:uuid:4d1a00b5-0000-4000-8000-000000000004'
SUBNQN = f'{BASENQN}:u4sub'
KIB = 1024
REPORT = []
DEVICES = {}

SUBSYS = {
    'id': 1, 'name': 'u4sub', 'subnqn': SUBNQN, 'serial': 'U4SERIAL0001', 'allow_any_host': True,
    'pi_enable': None, 'qid_max': None, 'ieee_oui': None, 'ana': None, 'hosts': [],
}
NAMESPACE = {
    'id': 1, 'nsid': 1, 'subsys': SUBSYS, 'device_type': 'FILE', 'device_path': str(NS_FILE),
    'dataset': None, 'relative_path': None, 'filesize': NS_BYTES,
    'device_uuid': '4d1a00b5-0000-4000-8000-0000000000aa',
    'device_nguid': '4d1a00b5-0000-4000-8000-0000000000bb',
    'enabled': True, 'locked': False,
}
# ANA ports bind each controller's own address; node A takes the first of the pair.
ANA_CHOICES = {'127.0.0.1': '127.0.0.3/127.0.0.4'}


def record(name, status='PASS', **details):
    row = {'test': name, 'status': status, **details}
    REPORT.append(row)
    (RESULTS / 'results.json').write_text(json.dumps(REPORT, indent=2) + '\n')
    print('U4_RESULT ' + json.dumps(row, sort_keys=True), flush=True)


def run(*args, timeout=120, binary=False, check=True):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{args!r}: {result.returncode}: {result.stderr.decode(errors="replace")}')
    return result if not check else (result.stdout if binary else result.stdout.decode())


def wait_for(predicate, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if result := predicate():
            return result
        time.sleep(0.2)
    raise TimeoutError('guest state transition timed out')


def port(index=1, service=4420, size=None, enabled=True):
    return {
        'id': index, 'index': index, 'addr_trtype': 'TCP', 'addr_trsvcid': service,
        'addr_traddr': '127.0.0.1', 'addr_adrfam': 'IPV4', 'inline_data_size': None,
        'max_queue_size': None, 'pi_enable': None, 'max_data_transfer_size': size, 'enabled': enabled,
    }


def render_ctx(ports, ana=False):
    """The `etc.generate('nvmet')` context for a non-HA or an HA node A system with ANA enabled."""
    ids = [p['id'] for p in ports]
    referrals = list(itertools.permutations(ids, 2))
    return {
        'failover.licensed': ana,
        'failover.node': 'A' if ana else 'MANUAL',
        'failover.status': 'MASTER' if ana else 'SINGLE',
        'nvmet.global.ana_active': ana,
        'nvmet.global.ana_enabled': ana,
        'nvmet.global.config': {
            'id': 1, 'basenqn': BASENQN, 'kernel': True, 'ana': ana, 'rdma': False, 'xport_referral': True,
        },
        'nvmet.global.rdma_enabled': False,
        'nvmet.host.query': [],
        'nvmet.namespace.query': [NAMESPACE],
        'nvmet.port.query': ports,
        'nvmet.port.usage': {
            'non_ana_port_ids': [] if ana else ids,
            'ana_port_ids': ids if ana else [],
            'non_ana_referrals': [] if ana else referrals,
            'ana_referrals': referrals + [(i, i) for i in ids] if ana else [],
        },
        'nvmet.subsys.firmware': '28.0.0-M',
        'nvmet.subsys.model': 'TrueNAS KVM VM',
        'nvmet.subsys.query': [SUBSYS],
        'nvmet.host_subsys.query': [],
        'nvmet.port_subsys.query': [{'id': p['id'], 'port': p, 'subsys': SUBSYS} for p in ports],
        'tcp.nvmet.port.transport_address_choices': ANA_CHOICES if ana else {},
        'rdma.nvmet.port.transport_address_choices': {},
    }


def render(ports, ana=False):
    """Render a configuration whose every port must be served."""
    assert kernel.write_config(render_ctx(ports, ana)) == []


def param_mdts(index):
    path = ROOT / 'ports' / str(index) / 'param_mdts'
    return int(path.read_text()) if path.exists() else None


def linked(index):
    return (ROOT / 'ports' / str(index) / 'subsystems' / SUBNQN).is_symlink()


def tcp_controllers():
    found = set()
    for path in Path('/sys/class/nvme').glob('nvme*'):
        try:
            if (path / 'transport').read_text().strip() == 'tcp':
                found.add(path.name)
        except FileNotFoundError:
            pass
    return found


def namespaces():
    return {p.name for p in Path('/sys/block').glob('nvme*') if re.fullmatch(r'nvme[0-9]+n[0-9]+', p.name)}


def connect(service=4420, address='127.0.0.1'):
    before, before_ns = tcp_controllers(), namespaces()
    run('nvme', 'connect', '-t', 'tcp', '-a', address, '-s', str(service), '-n', SUBNQN,
        '--nr-io-queues=1', '--queue-size=16', '--keep-alive-tmo=0', '--ctrl-loss-tmo=5',
        '--reconnect-delay=1')
    controller = '/dev/' + next(iter(wait_for(lambda: tcp_controllers() - before)))
    namespace = next(iter(wait_for(lambda: namespaces() - before_ns)))
    wait_for(lambda: Path('/dev/' + namespace).exists())
    DEVICES[controller] = namespace
    return controller


def disconnect(controller):
    namespace = DEVICES.pop(controller)
    run('nvme', 'disconnect', '-d', controller)
    wait_for(lambda: Path(controller).name not in tcp_controllers())
    wait_for(lambda: not Path('/dev/' + namespace).exists())


def connect_refused(service, address='127.0.0.1'):
    result = run('nvme', 'connect', '-t', 'tcp', '-a', address, '-s', str(service), '-n', SUBNQN,
                 '--nr-io-queues=1', '--ctrl-loss-tmo=1', check=False)
    return result.returncode != 0


def identify(controller):
    data = run('nvme', 'id-ctrl', controller, '-b', binary=True)
    assert len(data) == 4096
    namespace = DEVICES[controller]
    return {
        'mdts': data[77],
        'max_hw_sectors_kb': int(Path(f'/sys/block/{namespace}/queue/max_hw_sectors_kb').read_text()),
    }


def io_roundtrip(controller):
    payload = bytes((i * 37 + i // 257) & 255 for i in range(IO_BYTES))
    source, dest = Path('/tmp/u4-write.bin'), Path('/tmp/u4-read.bin')
    source.write_bytes(payload)
    device = '/dev/' + DEVICES[controller]
    run('dd', f'if={source}', f'of={device}', 'bs=1M', 'count=1', 'oflag=direct', 'status=none')
    run('dd', f'if={device}', f'of={dest}', 'bs=1M', 'count=1', 'iflag=direct', 'status=none')
    assert dest.read_bytes() == payload
    return hashlib.sha256(payload).hexdigest()


def record_port_attrs():
    record('port_attributes', attrs=sorted(p.name for p in (ROOT / 'ports' / '1').iterdir() if p.is_file()))


def expect_render_error(ctx, exc_type, err):
    try:
        kernel.write_config(ctx)
    except exc_type as e:
        assert e.errno == err, e
        return str(e)
    raise AssertionError('render unexpectedly succeeded')


def supported_suite():
    assert kernel.port_mdts_supported() is None
    record('capability_unknown_without_ports')

    one = [port(size=256 * KIB)]
    render(one)
    record_port_attrs()
    assert param_mdts(1) == 6 and linked(1)
    assert kernel.port_mdts_supported() is True
    controller = connect()
    ident = identify(controller)
    assert ident == {'mdts': 6, 'max_hw_sectors_kb': 256}, ident
    record('limit_written_before_link', param_mdts=6, **ident, io_sha256=io_roundtrip(controller))

    # The kernel refuses attribute writes on an enabled port, so an unchanged
    # value must not be written again.
    render(one)
    assert param_mdts(1) == 6 and linked(1)
    record('unchanged_rerender_on_enabled_port', io_sha256=io_roundtrip(controller))

    message = expect_render_error(render_ctx([port(size=1024 * KIB)]), OSError, errno.EACCES)
    assert param_mdts(1) == 6 and linked(1)
    record('kernel_rejects_change_on_enabled_port', error=message, io_sha256=io_roundtrip(controller))
    disconnect(controller)

    # The middleware maintenance path: disable, change, enable as separate renders.
    previous = 256 * KIB
    for size, expected in ((1024 * KIB, 8), (None, 0)):
        render([port(size=previous, enabled=False)])
        assert not linked(1)
        render([port(size=size, enabled=False)])
        assert param_mdts(1) == expected and not linked(1)
        render([port(size=size)])
        assert param_mdts(1) == expected and linked(1)
        controller = connect()
        ident = identify(controller)
        # Without a port limit the NVMe/TCP transport maximum (1 MiB) still applies.
        assert ident == {'mdts': 8, 'max_hw_sectors_kb': 1024}, ident
        record('disable_change_enable', requested=size, param_mdts=expected, **ident,
               io_sha256=io_roundtrip(controller))
        disconnect(controller)
        previous = size

    kernel.clear_config()
    ana = [port(size=256 * KIB)]
    render(ana, ana=True)
    assert not (ROOT / 'ports' / '1').exists()
    assert param_mdts(5001) == 6 and linked(5001)
    assert (ROOT / 'ports' / '5001' / 'addr_traddr').read_text().strip() == '127.0.0.3'
    controller = connect(address='127.0.0.3')
    ident = identify(controller)
    assert ident == {'mdts': 6, 'max_hw_sectors_kb': 256}, ident
    record('ana_derived_port_receives_limit', port_index=5001, param_mdts=6, **ident,
           io_sha256=io_roundtrip(controller))
    disconnect(controller)


def unsupported_suite():
    assert kernel.port_mdts_supported() is None
    record('capability_unknown_without_ports')

    legacy = [port()]
    render(legacy)
    record_port_attrs()
    assert param_mdts(1) is None and linked(1)
    assert kernel.port_mdts_supported() is False
    controller = connect()
    ident = identify(controller)
    record('legacy_null_port_serves', param_mdts_attribute=False, **ident, io_sha256=io_roundtrip(controller))

    limited = legacy + [port(index=2, service=4421, size=256 * KIB)]
    unserved = kernel.write_config(render_ctx(limited))
    assert unserved == ['127.0.0.1:4421'], unserved
    assert linked(1) and not linked(2)
    assert connect_refused(4421)
    record('limited_port_left_unserved', unserved=unserved, io_sha256_port1=io_roundtrip(controller))

    render(legacy + [port(index=2, service=4421)])
    assert linked(1) and linked(2)
    # Native multipath would join a second controller to the existing namespace
    # head, so drop port 1's path to prove I/O through port 2 alone.
    disconnect(controller)
    second = connect(4421)
    record('cleared_limit_links_port', io_sha256_port2=io_roundtrip(second))
    disconnect(second)

    # A served port whose limit becomes inapplicable stops serving instead of serving without it.
    assert kernel.write_config(render_ctx(limited)) == ['127.0.0.1:4421']
    assert linked(1) and not linked(2)
    assert connect_refused(4421)
    record('served_port_unlinked_when_limit_inapplicable')

    # A target start on this kernel with a stored limit serves every other port.
    kernel.clear_config()
    assert kernel.write_config(render_ctx(limited)) == ['127.0.0.1:4421']
    assert linked(1) and not linked(2)
    controller = connect()
    record('fresh_start_serves_other_ports', io_sha256_port1=io_roundtrip(controller))
    disconnect(controller)


def main():
    cmdline = Path('/proc/cmdline').read_text().split()
    assert 'u4_disposable=1' in cmdline, 'refusing to run outside the disposable guest'
    expect = next(arg.split('=', 1)[1] for arg in cmdline if arg.startswith('u4_expect='))
    disks = sorted(p.name for p in Path('/sys/block').iterdir() if not p.name.startswith(('loop', 'ram', 'zram')))
    assert not disks, f'unexpected block devices: {disks}'
    RESULTS.mkdir(exist_ok=True)

    NS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with NS_FILE.open('wb') as f:
        f.truncate(NS_BYTES)
    kernel.load_modules(['nvmet', 'nvmet_tcp'])
    run('mount', '-t', 'configfs', 'configfs', '/sys/kernel/config')
    record('environment', expect=expect, kernel=run('uname', '-r').strip(),
           renderer_sha256=hashlib.sha256(Path(kernel.__file__).read_bytes()).hexdigest())

    try:
        supported_suite() if expect == 'supported' else unsupported_suite()
        kernel.clear_config()
        assert not any((ROOT / 'ports').iterdir()) and not any((ROOT / 'subsystems').iterdir())
        for module in ('nvmet_tcp', 'nvmet'):
            kernel.unload_module(module)
        assert not ROOT.exists()
        record('teardown')
    except Exception as e:
        record('failure', status='FAIL', error=repr(e), traceback=traceback.format_exc())
        return 1
    record('complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())

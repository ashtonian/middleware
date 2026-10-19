import importlib.util
import os
import pathlib

import pytest

from middlewared.alert.source.nvmet import NVMetPortTransferSizeUnsupportedAlert
from middlewared.pytest.unit.middleware import Middleware
from middlewared.utils.nvmet import kernel
from middlewared.utils.nvmet.kernel import NvmetPortConfig, NvmetPortSubsysConfig, mdts_exponent, port_mdts_supported
from middlewared.utils.python import get_middlewared_dir

RENDER_CTX = {"failover.node": "MANUAL"}
SUBNQN = "nqn.2011-06.com.truenas:uuid:00000000-0000-4000-8000-000000000000:sub1"


def port_entry(max_data_transfer_size):
    return {
        "id": 1,
        "index": 1,
        "addr_trtype": "TCP",
        "addr_trsvcid": 4420,
        "addr_traddr": "192.0.2.1",
        "addr_adrfam": "IPV4",
        "inline_data_size": None,
        "max_queue_size": None,
        "pi_enable": None,
        "max_data_transfer_size": max_data_transfer_size,
        "enabled": True,
    }


def live_port(path: pathlib.Path, param_mdts: str | None):
    """A disabled configfs port as the kernel shows it, optionally without per-port MDTS support."""
    path.mkdir(parents=True)
    attrs = {
        "addr_trtype": "tcp",
        "addr_adrfam": "ipv4",
        "addr_traddr": "192.0.2.1",
        "addr_trsvcid": "4420",
        "param_pi_enable": "0",
    }
    if param_mdts is not None:
        attrs["param_mdts"] = param_mdts
    for name, value in attrs.items():
        (path / name).write_text(f"{value}\n")
    return path


@pytest.mark.parametrize(
    "size, exponent",
    [
        (8192, 1),
        (16384, 2),
        (262144, 6),
        (1048576, 8),
    ],
)
def test_mdts_exponent(size, exponent):
    assert mdts_exponent(size) == exponent


@pytest.mark.parametrize("size", [0, 4096, 6144, 12288, 1572864])
def test_mdts_exponent_rejects_unrepresentable(size):
    with pytest.raises(ValueError):
        mdts_exponent(size)


@pytest.mark.parametrize(
    "size, param_mdts",
    [
        (None, "0"),
        (262144, "6"),
        (1048576, "8"),
    ],
)
def test_map_attrs(size, param_mdts):
    assert NvmetPortConfig({}).map_attrs(port_entry(size), RENDER_CTX)["param_mdts"] == param_mdts


@pytest.mark.parametrize(
    "live, size, expected",
    [
        # The kernel shows -1 until the port is first enabled.
        ("-1", 262144, "6"),
        ("8", 262144, "6"),
        # Clearing a limit resets the kernel to its transport default.
        ("6", None, "0"),
        ("-1", None, "0"),
    ],
)
def test_update_writes_limit(tmp_path, live, size, expected):
    path = live_port(tmp_path / "1", live)

    NvmetPortConfig({}).update_attrs(path, port_entry(size), RENDER_CTX)

    assert (path / "param_mdts").read_text() == f"{expected}\n"


def test_update_skips_unchanged_limit(tmp_path, monkeypatch):
    path = live_port(tmp_path / "1", "6")
    written = []
    monkeypatch.setattr(pathlib.Path, "write_text", lambda self, *args, **kwargs: written.append(self.name))

    # An enabled port rejects attribute writes, so an unchanged limit must not be written.
    NvmetPortConfig({}).update_attrs(path, port_entry(262144), RENDER_CTX)

    assert written == []


@pytest.mark.parametrize("method", ["update", "create"])
@pytest.mark.parametrize("size, unserved", [(None, {}), (262144, {"1": "192.0.2.1:4420"})])
def test_unsupported_kernel(tmp_path, method, size, unserved):
    path = live_port(tmp_path / "1", None)
    config = NvmetPortConfig({})

    if method == "update":
        config.update_attrs(path, port_entry(size), RENDER_CTX)
    else:
        config.set_attrs(path, port_entry(size), 0, RENDER_CTX)

    # The port is still configured, but a limit it cannot apply keeps it from being served.
    assert not (path / "param_mdts").exists()
    assert config.unserved == unserved


def test_unserved_port_gets_no_subsystems(tmp_path, monkeypatch):
    root = tmp_path / "nvmet"
    monkeypatch.setattr(kernel, "NVMET_KERNEL_CONFIG_DIR", str(root))
    (root / "subsystems" / SUBNQN).mkdir(parents=True)
    for index in ("1", "2"):
        (root / "ports" / index / "subsystems").mkdir(parents=True)
    # Port 2 serves the subsystem from an earlier configuration.
    (root / "ports" / "2" / "subsystems" / SUBNQN).symlink_to(root / "subsystems" / SUBNQN)
    subsys = {"id": 1, "subnqn": SUBNQN, "ana": None}
    render_ctx = {
        "failover.status": "SINGLE",
        "nvmet.global.ana_enabled": False,
        "nvmet.global.rdma_enabled": False,
        "nvmet.port_subsys.query": [
            {"id": index, "port": port_entry(None) | {"id": index, "index": index}, "subsys": subsys}
            for index in (1, 2)
        ],
    }

    with NvmetPortSubsysConfig({"2": "192.0.2.1:4421"}).render(render_ctx):
        pass

    assert (root / "ports" / "1" / "subsystems" / SUBNQN).is_symlink()
    assert not (root / "ports" / "2" / "subsystems" / SUBNQN).exists()


@pytest.mark.parametrize("unserved", [[], ["192.0.2.1:4420", "192.0.2.1:4421"]])
def test_render_reports_unserved_ports(monkeypatch, unserved):
    spec = importlib.util.spec_from_file_location(
        "nvmet_kernel", os.path.join(get_middlewared_dir(), "etc_files", "nvmet_kernel.py")
    )
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    monkeypatch.setattr(renderer, "write_config", lambda render_ctx: unserved)
    middleware = Middleware()
    alert = middleware.services.alert

    renderer.render(None, middleware, {})

    if unserved:
        alert.oneshot_create.assert_called_once_with(
            NVMetPortTransferSizeUnsupportedAlert(ports="192.0.2.1:4420, 192.0.2.1:4421")
        )
        alert.oneshot_delete.assert_not_called()
    else:
        alert.oneshot_delete.assert_called_once_with("NVMetPortTransferSizeUnsupported", None)
        alert.oneshot_create.assert_not_called()


@pytest.mark.parametrize(
    "ports, expected",
    [
        (None, None),
        ({}, None),
        ({"1": "0"}, True),
        ({"1": None}, False),
    ],
)
def test_port_mdts_supported(tmp_path, monkeypatch, ports, expected):
    monkeypatch.setattr(kernel, "NVMET_KERNEL_CONFIG_DIR", str(tmp_path / "nvmet"))
    if ports is not None:
        (tmp_path / "nvmet" / "ports").mkdir(parents=True)
        for name, param_mdts in ports.items():
            live_port(tmp_path / "nvmet" / "ports" / name, param_mdts)

    assert port_mdts_supported() is expected

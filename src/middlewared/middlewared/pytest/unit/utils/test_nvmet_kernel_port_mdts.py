import pathlib

import pytest

from middlewared.service_exception import CallError
from middlewared.utils.nvmet import kernel
from middlewared.utils.nvmet.kernel import NvmetPortConfig, mdts_exponent, port_mdts_supported

RENDER_CTX = {"failover.node": "MANUAL"}


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
    assert NvmetPortConfig().map_attrs(port_entry(size), RENDER_CTX)["param_mdts"] == param_mdts


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

    NvmetPortConfig().update_attrs(path, port_entry(size), RENDER_CTX)

    assert (path / "param_mdts").read_text() == f"{expected}\n"


def test_update_skips_unchanged_limit(tmp_path, monkeypatch):
    path = live_port(tmp_path / "1", "6")
    written = []
    monkeypatch.setattr(pathlib.Path, "write_text", lambda self, *args, **kwargs: written.append(self.name))

    # An enabled port rejects attribute writes, so an unchanged limit must not be written.
    NvmetPortConfig().update_attrs(path, port_entry(262144), RENDER_CTX)

    assert written == []


@pytest.mark.parametrize("method", ["update", "create"])
def test_unsupported_kernel_without_limit(tmp_path, method):
    path = live_port(tmp_path / "1", None)

    if method == "update":
        NvmetPortConfig().update_attrs(path, port_entry(None), RENDER_CTX)
    else:
        NvmetPortConfig().set_attrs(path, port_entry(None), 0, RENDER_CTX)

    assert not (path / "param_mdts").exists()


@pytest.mark.parametrize("method", ["update", "create"])
def test_unsupported_kernel_with_limit(tmp_path, method):
    path = live_port(tmp_path / "1", None)

    with pytest.raises(CallError, match="port 1: the running kernel does not support max_data_transfer_size"):
        if method == "update":
            NvmetPortConfig().update_attrs(path, port_entry(262144), RENDER_CTX)
        else:
            NvmetPortConfig().set_attrs(path, port_entry(262144), 0, RENDER_CTX)

    assert not (path / "param_mdts").exists()


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

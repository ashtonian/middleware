import importlib
from unittest.mock import patch

from pydantic import ValidationError as PydanticValidationError
import pytest

from middlewared.api.current import NVMetPortCreateArgs, NVMetPortUpdateArgs
from middlewared.plugins.nvmet.port import NVMetPortService
from middlewared.pytest.unit.helpers import create_service
from middlewared.pytest.unit.middleware import Middleware
from middlewared.service import ValidationErrors

# `global` is a keyword, so the module cannot be named in an import statement.
NVMetGlobalService = importlib.import_module("middlewared.plugins.nvmet.global").NVMetGlobalService

ATTRIBUTE = "nvmet_port_update.max_data_transfer_size"


def port_entry(**kwargs):
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
        "max_data_transfer_size": None,
        "enabled": True,
    } | kwargs


@pytest.mark.parametrize("size", [None, 16384, 262144, 1048576])
def test_schema_accepts_limit(size):
    args = NVMetPortCreateArgs(
        nvmet_port_create={
            "addr_trtype": "TCP",
            "addr_traddr": "192.0.2.1",
            "max_data_transfer_size": size,
        }
    )

    assert args.nvmet_port_create.max_data_transfer_size == size


@pytest.mark.parametrize("size", [0, 4096, 8192, 1572864, 2097152, True, "262144"])
def test_schema_rejects_limit(size):
    with pytest.raises(PydanticValidationError):
        NVMetPortCreateArgs(
            nvmet_port_create={
                "addr_trtype": "TCP",
                "addr_traddr": "192.0.2.1",
                "max_data_transfer_size": size,
            }
        )
    with pytest.raises(PydanticValidationError):
        NVMetPortUpdateArgs(id=1, nvmet_port_update={"max_data_transfer_size": size})


def port_middleware(*, kernel=True, running=True, port_subsys=0):
    m = Middleware()
    m["nvmet.port.query"] = lambda *args: []
    m["nvmet.port_subsys.query"] = lambda *args: port_subsys
    m["nvmet.global.running"] = lambda: running
    m["nvmet.global.config"] = lambda: {"kernel": kernel}
    m["nvmet.global.rdma_capable"] = lambda: True
    return m


async def validate_port_update(m, old, new, mdts_supported=True):
    verrors = ValidationErrors()
    svc = create_service(m, NVMetPortService)
    with patch("middlewared.plugins.nvmet.port.port_mdts_supported", return_value=mdts_supported):
        await svc._NVMetPortService__validate(verrors, new, "nvmet_port_update", old=old)
    return [(e.attribute, e.errmsg) for e in verrors.errors]


@pytest.mark.parametrize("mdts_supported", [True, None])
@pytest.mark.parametrize("size", [None, 16384, 1048576])
@pytest.mark.asyncio
async def test_tcp_kernel_port_accepts_limit(size, mdts_supported):
    errors = await validate_port_update(
        port_middleware(),
        port_entry(),
        port_entry(max_data_transfer_size=size),
        mdts_supported,
    )

    assert errors == []


@pytest.mark.parametrize(
    "new, kernel, mdts_supported, message",
    [
        (
            port_entry(addr_trtype="RDMA", max_data_transfer_size=262144),
            True,
            True,
            "Maximum data transfer size is only supported on TCP ports.",
        ),
        (
            port_entry(addr_trtype="FC", addr_trsvcid=None, max_data_transfer_size=262144),
            True,
            True,
            "Maximum data transfer size is only supported on TCP ports.",
        ),
        (
            port_entry(max_data_transfer_size=262144),
            False,
            None,
            "Maximum data transfer size is not supported by the SPDK NVMe target.",
        ),
        (
            port_entry(max_data_transfer_size=262144),
            True,
            False,
            "The running kernel NVMe target does not support a maximum data transfer size.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_unsupported_limit_rejected(new, kernel, mdts_supported, message):
    errors = await validate_port_update(port_middleware(kernel=kernel), port_entry(), new, mdts_supported)

    assert errors == [(ATTRIBUTE, message)]


@pytest.mark.parametrize(
    "old, new",
    [
        # Legacy ports keep working whatever the backend or kernel supports.
        (port_entry(addr_trtype="RDMA"), port_entry(addr_trtype="RDMA", max_queue_size=128)),
        (port_entry(), port_entry(max_queue_size=128)),
    ],
)
@pytest.mark.parametrize("kernel, mdts_supported", [(True, False), (False, None)])
@pytest.mark.asyncio
async def test_null_limit_needs_no_support(old, new, kernel, mdts_supported):
    errors = await validate_port_update(port_middleware(kernel=kernel), old, new, mdts_supported)

    assert errors == []


@pytest.mark.parametrize(
    "old_size, new_size",
    [
        (None, 262144),
        (262144, 1048576),
        (262144, None),
    ],
)
@pytest.mark.asyncio
async def test_active_port_limit_change_rejected(old_size, new_size):
    errors = await validate_port_update(
        port_middleware(port_subsys=1),
        port_entry(max_data_transfer_size=old_size),
        port_entry(max_data_transfer_size=new_size),
    )

    assert errors == [
        (
            ATTRIBUTE,
            "Cannot change max_data_transfer_size on an active port.  Disable first to allow change.",
        )
    ]


@pytest.mark.asyncio
async def test_active_port_limit_change_rejected_when_disabling():
    errors = await validate_port_update(
        port_middleware(port_subsys=1),
        port_entry(),
        port_entry(enabled=False, max_data_transfer_size=262144),
    )

    assert errors == [
        (
            ATTRIBUTE,
            "Cannot change max_data_transfer_size on an active port.  Disable first to allow change.",
        )
    ]


@pytest.mark.parametrize("enabled, running", [(False, True), (True, False)])
@pytest.mark.asyncio
async def test_inactive_port_limit_change_allowed(enabled, running):
    errors = await validate_port_update(
        port_middleware(running=running, port_subsys=1),
        port_entry(enabled=enabled),
        port_entry(enabled=True, max_data_transfer_size=262144),
    )

    assert errors == []


def global_middleware(limited_ports):
    m = Middleware()
    m["nvmet.port.query"] = m._query_filter(limited_ports)
    m["system.cpu_flags"] = lambda: ["avx2"]
    return m


async def validate_backend_switch(m):
    verrors = ValidationErrors()
    svc = create_service(m, NVMetGlobalService)

    async def entitled(*args):
        return type("Entitlement", (), {"entitled": True, "message": None})()

    old = {"rdma": False, "ana": False, "kernel": True}
    with patch.object(svc, "call2", entitled):
        await svc._NVMetGlobalService__validate(verrors, old | {"kernel": False}, "nvmet_global_update", old=old)
    return [(e.attribute, e.errmsg) for e in verrors.errors]


@pytest.mark.asyncio
async def test_spdk_switch_rejected_while_ports_have_limit():
    errors = await validate_backend_switch(
        global_middleware(
            [
                {"index": 1, "max_data_transfer_size": 262144},
                {"index": 2, "max_data_transfer_size": None},
                {"index": 3, "max_data_transfer_size": 1048576},
            ]
        )
    )

    assert errors == [
        (
            "nvmet_global_update.kernel",
            "SPDK does not support a maximum data transfer size.  Clear it on port(s) #1, #3 first.",
        )
    ]


@pytest.mark.asyncio
async def test_spdk_switch_allowed_without_limits():
    errors = await validate_backend_switch(global_middleware([{"index": 1, "max_data_transfer_size": None}]))

    assert errors == []

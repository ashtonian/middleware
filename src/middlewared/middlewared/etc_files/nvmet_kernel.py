from middlewared.alert.source.nvmet import NVMetPortTransferSizeUnsupportedAlert
from middlewared.utils.nvmet.kernel import write_config


def render(service, middleware, render_ctx):
    if unserved := write_config(render_ctx):
        middleware.call_sync2(
            middleware.services.alert.oneshot_create,
            NVMetPortTransferSizeUnsupportedAlert(ports=', '.join(unserved)),
        )
    else:
        middleware.call_sync2(middleware.services.alert.oneshot_delete, 'NVMetPortTransferSizeUnsupported', None)

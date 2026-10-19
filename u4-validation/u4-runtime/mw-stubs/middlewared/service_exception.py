# Guest stub: the real module imports truenas_api_client, which the disposable
# guest does not have. The renderer only constructs CallError(errmsg, errno).
class CallError(Exception):
    def __init__(self, errmsg, errno=None, extra=None):
        super().__init__(errmsg)
        self.errmsg = errmsg
        self.errno = errno
        self.extra = extra

    def __str__(self):
        return f'[{self.errno}] {self.errmsg}'

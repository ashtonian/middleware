# Guest stub: the real module imports appliance-only packages. The checks use
# FILE namespaces, so the renderer never calls this.
def zvol_name_to_path(name):
    raise AssertionError(f'zvol namespaces are not used in the U4 guest: {name}')

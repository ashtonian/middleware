#!/bin/sh
# Stage U4 guest inputs into the lane's disposable builder volume from exact Git
# objects: middleware renderer files from the U4 commit and nvmet sources from
# the U3 base and candidate commits.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
middleware_repo=${MIDDLEWARE_REPO:?path to a truenas/middleware clone}
kernel_repo=${KERNEL_REPO:?path to a truenas/linux clone}
middleware_commit=${MIDDLEWARE_COMMIT:-4d1a00b562c0445a0993450817382422bb397a7a}
kernel_base=e43b65255bec4614c14447eb6152711e3e6e8124
kernel_candidate=9d9d9d7bd620d4c8ef6358e163ca78949e11c2f2
container=${U4_CONTAINER:-nvmeof-u3-local-20261018-a}
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

mw="$stage/u4/mw/middlewared"
mkdir -p "$mw/plugins/nvmet" "$mw/plugins/zfs_" "$mw/utils/nvmet"
for f in plugins/nvmet/__init__.py plugins/nvmet/constants.py utils/nvmet/__init__.py \
         utils/nvmet/kernel.py utils/nvmet/render_common.py; do
    git -C "$middleware_repo" show "$middleware_commit:src/middlewared/middlewared/$f" > "$mw/$f"
done
# Empty package markers stand in for package __init__ modules with appliance imports.
: > "$mw/__init__.py"; : > "$mw/plugins/__init__.py"; : > "$mw/plugins/zfs_/__init__.py"; : > "$mw/utils/__init__.py"
cp "$here/mw-stubs/middlewared/plugins/zfs_/utils.py" "$mw/plugins/zfs_/"

mkdir -p "$stage/u4/base-src" "$stage/u4/candidate-src"
files=$(git -C "$kernel_repo" diff --name-only "$kernel_base" "$kernel_candidate")
for f in $files; do
    git -C "$kernel_repo" show "$kernel_base:$f" > "$stage/u4/base-src/$(basename "$f")"
    git -C "$kernel_repo" show "$kernel_candidate:$f" > "$stage/u4/candidate-src/$(basename "$f")"
done
(cd "$stage/u4/base-src" && shasum -a 256 * > ../base-src.sha256)
(cd "$stage/u4/candidate-src" && shasum -a 256 * > ../candidate-src.sha256)
for f in u4_renderer_checks.py u4-guest-init.sh build-base-nvmet.sh boot-u4.sh extract-u4-results.py; do
    cp "$here/$f" "$stage/u4/"
done
COPYFILE_DISABLE=1 tar --no-xattrs -C "$stage" -cf - --exclude='._*' u4 \
    | docker exec -i "$container" sh -c 'rm -rf /work/u4/mw /work/u4/base-src /work/u4/candidate-src && tar -C /work -xf -'
echo "staged middleware $middleware_commit, kernel base $kernel_base, candidate $kernel_candidate"

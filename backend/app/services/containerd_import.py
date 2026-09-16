"""
Imports an admin-uploaded Docker image tar (`docker save ... -o model.tar`)
directly into the node's containerd image store, for the "upload a local
Docker image" custom-model deploy path - see POST /api/v1/deploy-custom-
image-upload in main.py. No registry involved: the backend pod has the
node's containerd socket mounted in (see k8s/backend-deployment.yaml and
helm/vela/templates/backend-deployment.yaml's containerdSocketAccess
block), and `ctr` talks to it directly over that socket - the image just
has to exist locally for create_image_deployment's imagePullPolicy: Never
to find it.

This only works because the target cluster is single-node: an image
imported this way is local to whichever node the backend pod is
scheduled on, and a pod for the resulting Deployment can only run there
too (no cross-node distribution). Fine for the on-prem/single-node case
this was built for; a multi-node cluster needs an actual registry
instead.
"""

import subprocess


def import_local_image(tar_path: str, name: str, tag: str = "latest") -> str:
    """Imports the image inside `tar_path` into containerd's "k8s.io"
    namespace (the one kubelet's CRI reads images from) and re-tags it as
    <name>:<tag> so create_image_deployment gets a predictable reference,
    independent of whatever the admin originally tagged it locally.
    Raises RuntimeError with ctr's own stderr/stdout on failure."""
    ref = f"{name}:{tag}"

    import_result = subprocess.run(
        ["ctr", "-n", "k8s.io", "images", "import", tar_path],
        capture_output=True, text=True,
    )
    if import_result.returncode != 0:
        raise RuntimeError(import_result.stderr.strip() or "ctr images import failed")

    # `ctr images import` names the image after whatever reference the
    # tar's own manifest carries (e.g. "docker.io/library/my-model:latest"),
    # not under our chosen name - pull it out of import's own stdout
    # ("unpacking <ref> (sha256:...)...done") so it can be re-tagged.
    imported_ref = None
    for line in import_result.stdout.splitlines():
        line = line.strip()
        if line.startswith("unpacking "):
            imported_ref = line.split()[1]
            break
    if not imported_ref:
        raise RuntimeError(f"Could not determine imported image reference from ctr output: {import_result.stdout!r}")

    tag_result = subprocess.run(
        ["ctr", "-n", "k8s.io", "images", "tag", imported_ref, ref],
        capture_output=True, text=True,
    )
    if tag_result.returncode != 0:
        raise RuntimeError(tag_result.stderr.strip() or "ctr images tag failed")

    return ref

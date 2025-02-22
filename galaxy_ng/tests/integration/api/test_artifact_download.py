import logging
import subprocess
import tempfile
from unittest.mock import patch

import pytest
from orionutils.generator import build_collection, randstr

from ..conftest import is_hub_4_5
from ..constants import USERNAME_PUBLISHER
from ..utils import (
    CapturingGalaxyError,
    CollectionInspector,
    get_client,
    set_certification,
    wait_for_task
)

logger = logging.getLogger(__name__)


# TODO Refactor get_client to provide access to bearer token
@pytest.mark.deployment_standalone
def test_download_artifact(ansible_config, upload_artifact):
    config = ansible_config("partner_engineer")
    api_client = get_client(config, request_token=True, require_auth=True)

    # create, upload and certify a collection
    namespace = USERNAME_PUBLISHER
    name = f"{USERNAME_PUBLISHER}_{randstr(8)}"
    version = "1.0.0"
    artifact = build_collection("skeleton", config={
        "namespace": namespace,
        "name": name,
        "version": version,
    })

    with patch("ansible.galaxy.api.GalaxyError", CapturingGalaxyError):
        try:
            resp = upload_artifact(config, api_client, artifact)
        except CapturingGalaxyError as capture:
            error_body = capture.http_error.read()
            logger.error("Upload failed with error response: %s", error_body)
            raise
        else:
            resp = wait_for_task(api_client, resp)
            assert resp["state"] == "completed"

    hub_4_5 = is_hub_4_5(ansible_config)

    set_certification(api_client, artifact, hub_4_5=hub_4_5)

    # download collection
    config = ansible_config("basic_user")

    with tempfile.TemporaryDirectory() as dir:
        api_root = config["url"]
        filename = f"{namespace}-{name}-{version}.tar.gz"
        tarball_path = f"{dir}/{filename}"
        url = f"{api_root}v3/plugin/ansible/content/published/collections/artifacts/{filename}"

        cmd = [
            "curl",
            "--retry",
            "5",
            "-L",
            "-H",
            "'Content-Type: application/json'",
            "-u",
            f"{config['username']}:{config['password']}",
            "-o",
            tarball_path,
            url,
            "--insecure"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        returncode = proc.wait()
        assert returncode == 0

        # Extract tarball, verify information in manifest
        ci = CollectionInspector(tarball=tarball_path)
        assert ci.namespace == namespace
        assert ci.name == name
        assert ci.version == version


# TODO: make download logic more DRY in these tests
@pytest.mark.min_hub_version("4.6dev")
@pytest.mark.all
def test_download_artifact_validated(ansible_config, artifact, upload_artifact):
    config = ansible_config("partner_engineer")
    api_client = get_client(config, request_token=True, require_auth=True)

    resp = upload_artifact(config, api_client, artifact)
    resp = wait_for_task(api_client, resp)

    set_certification(api_client, artifact, level="validated")

    # download collection
    config = ansible_config("basic_user")

    with tempfile.TemporaryDirectory() as dir:
        api_root = config["url"]
        filename = f"{artifact.namespace}-{artifact.name}-{artifact.version}.tar.gz"
        tarball_path = f"{dir}/{filename}"
        url = f"{api_root}v3/plugin/ansible/content/validated/collections/artifacts/{filename}"

        cmd = [
            "curl",
            "--retry",
            "5",
            "-L",
            "-H",
            "'Content-Type: application/json'",
            "-u",
            f"{config['username']}:{config['password']}",
            "-o",
            tarball_path,
            url,
            "--insecure"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        returncode = proc.wait()
        assert returncode == 0

        # Extract tarball, verify information in manifest
        ci = CollectionInspector(tarball=tarball_path)
        assert ci.namespace == artifact.namespace
        assert ci.name == artifact.name
        assert ci.version == artifact.version

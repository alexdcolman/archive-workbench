from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).parents[1]


def _compose_services() -> dict:
    return yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]


def test_container_variants_keep_user_data_outside_images() -> None:
    cpu_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    gpu_dockerfile = (ROOT / "Dockerfile.gpu").read_text(encoding="utf-8")
    services = _compose_services()
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert set(services) == {"app-cpu", "app-gpu"}
    for service_name in ("app-cpu", "app-gpu"):
        service = services[service_name]
        assert service["ports"] == ["127.0.0.1:8501:8501"]
        volumes = service["volumes"]
        assert {
            "type": "bind",
            "source": "./ArchiveWorkbenchData",
            "target": "/workspace",
        } in volumes
        assert {
            "type": "bind",
            "source": "${AW_SELECTED_PROJECT_HOST:-./ArchiveWorkbenchData/Projects}",
            "target": "/selected-project",
        } in volumes
        assert service["environment"]["ARCHIVE_WORKBENCH_WORKSPACE_ROOT"] == "/workspace"
        assert service["environment"]["ARCHIVE_WORKBENCH_PROJECTS_ROOT"] == "/workspace/Projects"
        assert (
            service["environment"]["ARCHIVE_WORKBENCH_DOCUMENT_IMPORT_ROOT"]
            == "/workspace/Imports/Documents"
        )
        assert (
            service["environment"]["ARCHIVE_WORKBENCH_AUDIOVISUAL_IMPORT_ROOT"]
            == "/workspace/Imports/AudioVideo"
        )
        assert (
            service["environment"]["ARCHIVE_WORKBENCH_PREFERENCES_PATH"]
            == "/workspace/Settings/preferences.json"
        )
        assert (
            service["environment"]["ARCHIVE_WORKBENCH_SELECTED_PROJECT_ROOT"]
            == "${AW_SELECTED_PROJECT_CONTAINER:-}"
        )
        assert service["user"] == "${AW_UID:-1000}:${AW_GID:-1000}"

    assert services["app-cpu"]["environment"]["ARCHIVE_WORKBENCH_RUNTIME_VARIANT"] == "cpu"
    assert services["app-gpu"]["environment"]["ARCHIVE_WORKBENCH_RUNTIME_VARIANT"] == "gpu"
    assert services["app-gpu"]["gpus"] == "all"
    assert services["app-cpu"]["profiles"] == ["cpu"]
    assert services["app-gpu"]["profiles"] == ["gpu"]
    assert "ArchiveWorkbenchData" in dockerignore
    assert "/ArchiveWorkbenchData/" in gitignore
    assert "pilot_data" in dockerignore
    assert "project_data" in dockerignore
    for dockerfile in (cpu_dockerfile, gpu_dockerfile):
        assert "COPY pilot_data" not in dockerfile
        assert "COPY ArchiveWorkbenchData" not in dockerfile


def test_cpu_container_forces_cpu_surya_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "docker" / "container-entrypoint.sh").read_text(encoding="utf-8")

    for extra in (
        "extraction",
        "streamlit",
        "semantic",
        "tiff",
        "discovery",
        "audiovisual",
        "platform",
    ):
        assert extra in dockerfile
    assert "/opt/archive-workbench/.venv-surya" in dockerfile
    assert 'surya-ocr==0.22.1' in dockerfile
    assert dockerfile.count("https://download.pytorch.org/whl/cpu") == 2
    assert "main_torch=cpu" in dockerfile
    assert "torch.version.cuda is None" in dockerfile
    main_cpu_index = dockerfile.index("https://download.pytorch.org/whl/cpu")
    main_extras = dockerfile.index(
        'python -m pip install ".[extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"'
    )
    assert main_cpu_index < main_extras
    assert "ffmpeg" in dockerfile
    assert "tesseract-ocr-spa" in dockerfile
    assert "libvips42" in dockerfile
    assert "archive-workbench review-app" in entrypoint
    assert "--host 0.0.0.0" in entrypoint
    assert "/workspace/Projects" in entrypoint
    assert "ARCHIVE_WORKBENCH_SELECTED_PROJECT_ROOT" in entrypoint
    assert 'review-app "$selected_project"' in entrypoint
    assert "config/decisions.yaml" in entrypoint


def test_gpu_container_uses_cuda_cudnn_and_cuda_surya_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile.gpu").read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04" in dockerfile
    assert 'surya-ocr==0.22.1' in dockerfile
    assert "https://download.pytorch.org/whl/cu128" in dockerfile
    assert "torch.version.cuda is not None" in dockerfile
    assert "ctranslate2" in dockerfile
    assert "ffmpeg" in dockerfile
    assert "tesseract-ocr-spa" in dockerfile
    assert "libvips42" in dockerfile


def test_cross_platform_launchers_select_prebuilt_cpu_or_gpu_images() -> None:
    cpu_tag = (ROOT / "docker" / "image-tag.txt").read_text(encoding="utf-8").strip()
    gpu_tag = (ROOT / "docker" / "gpu-image-tag.txt").read_text(encoding="utf-8").strip()
    assert cpu_tag == "0.89.0-rc80-cpu"
    assert gpu_tag == "0.89.0-rc80-gpu"

    cpu_image = f"ghcr.io/alexdcolman/archive-workbench:{cpu_tag}"
    gpu_image = f"ghcr.io/alexdcolman/archive-workbench:{gpu_tag}"
    cpu_launchers = (
        ROOT / "Start Archive Workbench - Windows.bat",
        ROOT / "Start Archive Workbench - macOS.command",
        ROOT / "Start Archive Workbench - Linux.sh",
    )
    for launcher in cpu_launchers:
        source = launcher.read_text(encoding="utf-8")
        assert cpu_image in source
        assert "ArchiveWorkbenchData" in source
        assert "docker pull" in source
        assert "docker image inspect" in source
        assert "docker compose" in source
        assert "--profile cpu" in source or (
            "AW_PROFILE=cpu" in source and "--profile %AW_PROFILE%" in source
        )
        assert "app-cpu" in source
        assert "AW_SELECTED_PROJECT" in source
        assert "docker compose build" not in source
        assert "http://localhost:8501" in source

    gpu_launchers = (
        ROOT / "Start Archive Workbench - GPU - Windows.bat",
        ROOT / "Start Archive Workbench - GPU - Linux.sh",
    )
    for launcher in gpu_launchers:
        source = launcher.read_text(encoding="utf-8")
        assert gpu_image in source
        assert "--gpus all" in source
        assert "nvidia-smi" in source
        assert "--profile gpu" in source or (
            "AW_PROFILE=gpu" in source and "--profile %AW_PROFILE%" in source
        )
        assert "app-gpu" in source
        assert "AW_SELECTED_PROJECT" in source
        assert "docker image inspect" in source
        assert "docker compose build" not in source

    first_start = (ROOT / "FIRST_START.txt").read_text(encoding="utf-8")
    assert "Windows" in first_start
    assert "macOS" in first_start
    assert "Linux" in first_start
    assert "Projects" in first_start
    assert "Imports/Documents" in first_start
    assert "Imports/AudioVideo" in first_start
    assert "imagen CPU" in first_start
    assert "imagen GPU" in first_start
    assert "macOS" in first_start and "NVIDIA" in first_start
    assert "Elegir un proyecto" in first_start
    assert "Google Drive" in first_start


def test_container_shell_scripts_have_valid_syntax() -> None:
    checks = (
        ("sh", ROOT / "docker" / "container-entrypoint.sh"),
        ("sh", ROOT / "docker" / "select-project-linux.sh"),
        ("bash", ROOT / "docker" / "select-project-macos.sh"),
        ("sh", ROOT / "Start Archive Workbench - Linux.sh"),
        ("sh", ROOT / "Start Archive Workbench - GPU - Linux.sh"),
        ("sh", ROOT / "Stop Archive Workbench - Linux.sh"),
        ("bash", ROOT / "Start Archive Workbench - macOS.command"),
        ("bash", ROOT / "Stop Archive Workbench - macOS.command"),
    )
    for shell, path in checks:
        result = subprocess.run(
            [shell, "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_container_publish_workflow_targets_cpu_and_gpu_images() -> None:
    workflow_text = (ROOT / ".github" / "workflows" / "publish-container.yml").read_text(
        encoding="utf-8"
    )
    workflow = yaml.safe_load(workflow_text)

    assert "workflow_dispatch" in workflow[True]
    assert "release" in workflow[True]
    assert "packages: write" in workflow_text
    assert "ghcr.io/${{ github.repository }}" in workflow_text
    assert "linux/amd64,linux/arm64" in workflow_text
    assert "platforms: linux/amd64" in workflow_text
    assert "docker/image-tag.txt" in workflow_text
    assert "docker/gpu-image-tag.txt" in workflow_text
    assert "file: ./Dockerfile.gpu" in workflow_text
    assert "scope=archive-workbench-cpu" in workflow_text
    assert "scope=archive-workbench-gpu" in workflow_text


def test_container_distribution_files_are_present() -> None:
    required = (
        "Dockerfile",
        "Dockerfile.gpu",
        "compose.yaml",
        ".dockerignore",
        "FIRST_START.txt",
        "Start Archive Workbench - Windows.bat",
        "Start Archive Workbench - GPU - Windows.bat",
        "Stop Archive Workbench - Windows.bat",
        "Start Archive Workbench - macOS.command",
        "Stop Archive Workbench - macOS.command",
        "Start Archive Workbench - Linux.sh",
        "Start Archive Workbench - GPU - Linux.sh",
        "Stop Archive Workbench - Linux.sh",
        "docker/container-entrypoint.sh",
        "docker/select-project-linux.sh",
        "docker/select-project-macos.sh",
        "docker/select-project-windows.ps1",
        "docker/image-tag.txt",
        "docker/gpu-image-tag.txt",
        ".github/workflows/publish-container.yml",
    )
    for relative in required:
        assert (ROOT / relative).is_file(), relative


def test_host_project_picker_mounts_only_the_selected_project() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    for service_name in ("app-cpu", "app-gpu"):
        service = services[service_name]
        assert {
            "type": "bind",
            "source": "${AW_SELECTED_PROJECT_HOST:-./ArchiveWorkbenchData/Projects}",
            "target": "/selected-project",
        } in service["volumes"]
        assert (
            service["environment"]["ARCHIVE_WORKBENCH_SELECTED_PROJECT_ROOT"]
            == "${AW_SELECTED_PROJECT_CONTAINER:-}"
        )

    linux = (ROOT / "docker" / "select-project-linux.sh").read_text(encoding="utf-8")
    macos = (ROOT / "docker" / "select-project-macos.sh").read_text(encoding="utf-8")
    windows = (ROOT / "docker" / "select-project-windows.ps1").read_text(encoding="utf-8")
    for source in (linux, macos, windows):
        assert "config/decisions.yaml" in source or "config\\decisions.yaml" in source
        assert "Google Drive" in source
        assert "OneDrive" in source
        assert "Dropbox" in source
    assert "zenity --file-selection --directory" in linux
    assert "choose folder" in macos
    assert "FolderBrowserDialog" in windows


def test_cpu_and_gpu_images_bundle_their_surya_inference_server() -> None:
    cpu = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    gpu = (ROOT / "Dockerfile.gpu").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "ghcr.io/ggml-org/llama.cpp:server-b10524" in cpu
    assert "COPY --from=llama-server /app /opt/llama" in cpu
    assert "LLAMA_CPP_BINARY=/opt/llama/llama-server" in cpu
    assert "SURYA_INFERENCE_BACKEND=llamacpp" in cpu
    assert 'LD_LIBRARY_PATH="/opt/llama"' in cpu
    assert "test -f /opt/llama/libllama-server-impl.so" in cpu

    assert "ghcr.io/ggml-org/llama.cpp:server-cuda12-b10524" in gpu
    assert "COPY --from=llama-server /app /opt/llama" in gpu
    assert "LLAMA_CPP_BINARY=/opt/llama/llama-server" in gpu
    assert "SURYA_INFERENCE_BACKEND=llamacpp" in gpu
    assert 'LD_LIBRARY_PATH="/opt/llama:/usr/local/cuda/lib64"' in gpu
    assert "test -f /opt/llama/libllama-server-impl.so" in gpu

    assert "ARCHIVE_WORKBENCH_SURYA_BACKEND: llamacpp" in compose


def test_linux_project_picker_can_choose_existing_project_without_gui_state_leaking(tmp_path: Path) -> None:
    project = tmp_path / "Proyecto con espacios"
    (project / "config").mkdir(parents=True)
    (project / "config" / "decisions.yaml").write_text("project_id: demo\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_zenity = fake_bin / "zenity"
    fake_zenity.write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        "  *\" --list \"*) printf '%s\\n' 'Abrir un proyecto existente' ;;\n"
        "  *\" --file-selection \"*) printf '%s\\n' \"$FAKE_PROJECT\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_zenity.chmod(0o755)

    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "FAKE_PROJECT": str(project),
    }
    result = subprocess.run(
        ["sh", str(ROOT / "docker" / "select-project-linux.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == str(project)
    assert result.stderr == ""


def test_linux_project_picker_can_open_general_start(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_zenity = fake_bin / "zenity"
    fake_zenity.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'Abrir el inicio de Archive Workbench'\n",
        encoding="utf-8",
    )
    fake_zenity.chmod(0o755)

    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["sh", str(ROOT / "docker" / "select-project-linux.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert result.stdout == ""

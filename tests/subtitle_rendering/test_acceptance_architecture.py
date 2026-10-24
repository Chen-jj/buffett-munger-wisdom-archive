"""SR-06 AST boundaries; no source file is executed by these checks."""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2] / "src" / "subtitle_rendering"
FEATURES = {"acquisition", "media_download", "transcription", "translation", "srt_processing", "orchestration", "cli", "webui"}


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


@pytest.mark.parametrize("path", sorted(ROOT.rglob("*.py")), ids=lambda path: str(path.relative_to(ROOT)))
def test_production_module_imports_do_not_cross_other_functional_modules(path):
    tree = ast.parse(path.read_text())
    for name in imports(tree):
        parts = name.split(".")
        assert not FEATURES.intersection(parts), (path, name)
        if "archive_core" in parts:
            assert parts[parts.index("archive_core") + 1] in ("domain", "application", "interfaces")


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_pure_layers_do_not_import_or_call_concrete_external_capabilities(layer):
    for path in (ROOT / layer).glob("*.py"):
        tree = ast.parse(path.read_text())
        for name in imports(tree):
            assert not {"PIL", "pysubs2", "fontTools", "subprocess", "requests", "httpx", "urllib"}.intersection(name.split(".")), (path, name)
            assert not name.startswith("subtitle_rendering.infrastructure")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                assert not (isinstance(node.func, ast.Name) and node.func.id == "open"), path
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in ("write_bytes", "write_text", "mkdir", "unlink", "rmtree", "system", "popen"), path


def test_no_private_shell_runner_automatic_cleanup_or_hardware_encoder_in_production_ast():
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in ("unlink", "rmtree", "remove", "system", "popen", "Popen"), path
                assert not any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords), path
        # The renderer also contains a rejection guard naming forbidden flags. Inspect only
        # command-construction methods, not those defensive comparisons or documentation.
        for method in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                       and node.name in ("build_command", "render_transparent_frame", "tool_identity")):
            values = [node.value for node in ast.walk(method) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
            assert not {"-y", "-shortest", "h264_videotoolbox", "h264_nvenc", "h264_qsv", "cuda"}.intersection(values), path


def test_public_handler_has_no_layout_media_reuse_or_concrete_adapter_imports():
    path = ROOT / "interfaces" / "workflow.py"
    tree = ast.parse(path.read_text())
    assert set(imports(tree)) == {"dataclasses", "subtitle_rendering.application.workflow"}
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    handler = classes["SubtitleRenderingCommandHandler"]
    calls = [node.func.attr for node in ast.walk(handler) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert calls == ["execute"]


def test_actual_renderer_process_calls_are_only_shared_argv_capabilities():
    path = ROOT / "infrastructure" / "ffmpeg.py"
    names = set(imports(ast.parse(path.read_text())))
    assert "infrastructure.infrastructure.process" in names
    assert "subprocess" not in names and "os" not in names

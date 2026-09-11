import ast
import hashlib
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
TASK_HISTORY_HELPERS = {
    "_find_final_task_video",
    "_build_video_download_name",
    "_build_restore_upload_requirements",
    "_get_unmet_restore_upload_requirements",
    "_safe_load_task_status",
    "_resolve_task_directory",
    "_list_task_files",
    "_task_file_signature",
    "_build_task_file_archive",
    "_task_file_preview_kind",
    "_resolve_task_file_for_preview",
}
TASK_HISTORY_CONSTANTS = {
    "_FINAL_VIDEO_PATTERN",
    "_DOWNLOAD_FILENAME_INVALID_PATTERN",
    "_WINDOWS_RESERVED_FILENAMES",
    "VOICE_MODE_TTS",
    "VOICE_MODE_UPLOAD",
    "VOICE_MODE_NONE",
    "TASK_STATUS_FILENAME",
    "TASK_FILE_VIEW_LIMIT",
}


def _load_task_history_helpers():
    """
    从 WebUI 入口中隔离加载不依赖 Streamlit 的任务历史纯函数。

    直接导入 Main.py 会执行整套页面渲染。测试只编译目标常量和函数，既验证
    合并后的真实实现，也避免为了单元测试重新拆出一个只有少量函数的生产模块。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in TASK_HISTORY_CONSTANTS
            for target in node.targets
        ):
            selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in TASK_HISTORY_HELPERS:
            selected_nodes.append(node)

    namespace = {
        "json": __import__("json"),
        "hashlib": hashlib,
        "mimetypes": __import__("mimetypes"),
        "logger": __import__("logging").getLogger(__name__),
        "os": os,
        "re": re,
        "Mapping": Mapping,
        "Path": Path,
        "tempfile": tempfile,
        "zipfile": zipfile,
    }
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace


TASK_HISTORY_NAMESPACE = _load_task_history_helpers()
find_final_task_video = TASK_HISTORY_NAMESPACE["_find_final_task_video"]
build_video_download_name = TASK_HISTORY_NAMESPACE["_build_video_download_name"]
windows_reserved_filenames = TASK_HISTORY_NAMESPACE["_WINDOWS_RESERVED_FILENAMES"]
build_restore_upload_requirements = TASK_HISTORY_NAMESPACE[
    "_build_restore_upload_requirements"
]
get_unmet_restore_upload_requirements = TASK_HISTORY_NAMESPACE[
    "_get_unmet_restore_upload_requirements"
]
safe_load_task_status = TASK_HISTORY_NAMESPACE["_safe_load_task_status"]
list_task_files = TASK_HISTORY_NAMESPACE["_list_task_files"]
build_task_file_archive = TASK_HISTORY_NAMESPACE["_build_task_file_archive"]
task_file_preview_kind = TASK_HISTORY_NAMESPACE["_task_file_preview_kind"]
resolve_task_file_for_preview = TASK_HISTORY_NAMESPACE["_resolve_task_file_for_preview"]


def test_find_final_task_video_ignores_intermediate_files(tmp_path):
    """任务历史只能把 final 成片识别为完成，不能使用合成中间文件。"""
    for file_name in (
        "combined-1.mp4",
        "temp-clip-1.mp4",
        "final-1TEMP_MPY_wvf_snd.mp4",
    ):
        (tmp_path / file_name).touch()

    assert find_final_task_video(str(tmp_path)) == ""


def test_find_final_task_video_returns_first_numbered_output(tmp_path):
    """多成片任务与运行时结果保持一致，默认播放序号最小的最终视频。"""
    (tmp_path / "final-10.mp4").touch()
    (tmp_path / "final-2.mp4").touch()
    (tmp_path / "final-1.mp4").touch()

    assert find_final_task_video(str(tmp_path)) == str(tmp_path / "final-1.mp4")


def test_build_video_download_name_uses_subject_and_output_index():
    assert (
        build_video_download_name("A day: in / Shanghai?", 2, 3)
        == "A day in Shanghai-2.mp4"
    )


def test_build_video_download_name_handles_empty_and_long_subjects():
    assert build_video_download_name("  ...  ", 1, 1) == "video.mp4"
    assert len(build_video_download_name("a" * 100, 1, 1)) == 84


def test_build_video_download_name_avoids_windows_reserved_names():
    # 使用官方规则的显式清单，避免测试复制生产代码的 range/comprehension；
    # 如果实现误写范围，集合相等断言会立即失败，而不是与实现一起漏测。
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "COM¹",
        "COM²",
        "COM³",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
        "LPT¹",
        "LPT²",
        "LPT³",
    }
    assert windows_reserved_filenames == reserved_names

    for reserved_name in reserved_names:
        assert (
            build_video_download_name(reserved_name.lower(), 1, 1)
            == f"_{reserved_name.lower()}.mp4"
        )
        assert (
            build_video_download_name(f"{reserved_name}.topic", 2, 3)
            == f"_{reserved_name}.topic-2.mp4"
        )

    assert build_video_download_name("con .topic", 1, 1) == "_con .topic.mp4"


def test_build_video_download_name_does_not_overmatch_similar_names():
    """只处理 Windows 真实保留名，不能误伤相邻但合法的普通主题。"""

    for safe_name in ("COM0", "COM10", "LPT0", "LPT10", "COM⁴", "LPT⁴"):
        assert build_video_download_name(safe_name, 1, 1) == f"{safe_name}.mp4"


def test_restore_requirements_block_missing_uploaded_files():
    params = {
        "video_source": "local",
        "custom_audio_file": "/old-task/custom-audio.wav",
        "voice_name": "zh-CN-XiaoxiaoNeural-Female",
    }
    requirements = build_restore_upload_requirements(params)

    assert get_unmet_restore_upload_requirements(
        requirements,
        video_source="local",
        voice_name=params["voice_name"],
        has_local_materials=False,
        has_custom_audio=False,
    ) == {"local_materials", "custom_audio"}


def test_restore_requirements_allow_explicit_replacements():
    requirements = build_restore_upload_requirements(
        {
            "video_source": "local",
            "custom_audio_file": "/old-task/custom-audio.wav",
            "voice_name": "zh-CN-XiaoxiaoNeural-Female",
        }
    )

    assert not get_unmet_restore_upload_requirements(
        requirements,
        video_source="pexels",
        voice_name="en-US-JennyNeural-Female",
        has_local_materials=False,
        has_custom_audio=False,
    )


def test_restore_requirements_require_file_in_upload_voice_mode():
    """恢复上传配音任务时，继续使用上传模式必须重新选择音频文件。"""
    requirements = build_restore_upload_requirements(
        {
            "video_source": "pexels",
            "custom_audio_file": "/old-task/custom-audio.wav",
            "voice_name": "zh-CN-XiaoxiaoNeural-Female",
        }
    )

    assert get_unmet_restore_upload_requirements(
        requirements,
        video_source="pexels",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
        has_local_materials=False,
        has_custom_audio=False,
        voice_mode="upload",
    ) == {"custom_audio"}


def test_restore_requirements_allow_replacing_upload_with_other_voice_modes():
    """用户主动切换到自动配音或无配音时，不再强制恢复历史上传文件。"""
    requirements = build_restore_upload_requirements(
        {
            "video_source": "pexels",
            "custom_audio_file": "/old-task/custom-audio.wav",
            "voice_name": "zh-CN-XiaoxiaoNeural-Female",
        }
    )

    for voice_mode in ("tts", "none"):
        assert not get_unmet_restore_upload_requirements(
            requirements,
            video_source="pexels",
            voice_name="zh-CN-XiaoxiaoNeural-Female",
            has_local_materials=False,
            has_custom_audio=False,
            voice_mode=voice_mode,
        )


def test_history_status_record_survives_runtime_state_loss(tmp_path):
    payload = {
        "task_id": "failed-task",
        "state": -1,
        "progress": 40,
        "failed_stage": "materials",
        "error": "gateway temporarily unavailable",
    }
    (tmp_path / "task-status.json").write_text(json.dumps(payload), encoding="utf-8")

    assert safe_load_task_status(str(tmp_path)) == payload


def test_task_file_listing_keeps_downloads_inside_the_task_directory(tmp_path):
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "completed-task"
    task_dir.mkdir(parents=True)
    artifact = task_dir / "final-1.mp4"
    artifact.write_bytes(b"video")
    external_file = tmp_path / "outside.txt"
    external_file.write_text("private", encoding="utf-8")

    TASK_HISTORY_NAMESPACE["utils"] = SimpleNamespace(
        task_dir=lambda: str(tasks_root)
    )
    files, is_truncated = list_task_files(str(task_dir))

    assert files == [
        {
            "path": str(artifact.resolve()),
            "name": "final-1.mp4",
            "size": len(b"video"),
        }
    ]
    assert is_truncated is False

    try:
        (task_dir / "outside-link.txt").symlink_to(external_file)
    except (NotImplementedError, OSError):
        return

    files, _ = list_task_files(str(task_dir))
    assert [file["name"] for file in files] == ["final-1.mp4"]


def test_task_file_archive_preserves_relative_paths(tmp_path):
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "completed-task"
    nested_dir = task_dir / "subtitles"
    nested_dir.mkdir(parents=True)
    (task_dir / "final-1.mp4").write_bytes(b"video")
    (nested_dir / "subtitle.srt").write_text("subtitle", encoding="utf-8")

    TASK_HISTORY_NAMESPACE["utils"] = SimpleNamespace(
        task_dir=lambda: str(tasks_root)
    )
    files, is_truncated = list_task_files(str(task_dir), limit=None)
    archive_path = build_task_file_archive(str(task_dir), files)
    try:
        assert is_truncated is False
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.namelist() == ["final-1.mp4", "subtitles/subtitle.srt"]
            assert archive.read("final-1.mp4") == b"video"
            assert archive.read("subtitles/subtitle.srt") == b"subtitle"
    finally:
        os.remove(archive_path)


def test_task_file_preview_supports_media_and_text_inside_task_directory(tmp_path):
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "completed-task"
    task_dir.mkdir(parents=True)
    image_file = task_dir / "1-image.png"
    video_file = task_dir / "final-1.mp4"
    text_file = task_dir / "script.json"
    image_file.write_bytes(b"png")
    video_file.write_bytes(b"video")
    text_file.write_text("{}", encoding="utf-8")

    TASK_HISTORY_NAMESPACE["utils"] = SimpleNamespace(
        task_dir=lambda: str(tasks_root)
    )

    assert task_file_preview_kind(str(image_file)) == "image"
    assert task_file_preview_kind(str(video_file)) == "video"
    assert task_file_preview_kind(str(text_file)) == "text"
    assert resolve_task_file_for_preview(str(task_dir), str(image_file)) == str(
        image_file.resolve()
    )
    assert resolve_task_file_for_preview(str(task_dir), str(tmp_path / "outside.png")) == ""

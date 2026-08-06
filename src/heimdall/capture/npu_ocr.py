"""OpenVINO/NPU OCR engine for rapidocr (map #69, prototype #70).

Port of the proto's `NpuOpenVINOSession` (`proto/rapid-ocr-npu` bench) into
the main tree: rapidocr's det/cls/rec factories are told to build OpenVINO
sessions that compile for the **NPU** device, with a per-shape compiled-model
cache. Anything that can't run (no openvino, no NPU device) degrades via
`install_npu_engine` returning False — the caller falls back to CPU.

The NPU driver compiles per input shape; real windows vary in size, so the
cache keeps the last `CACHE_SIZE` shapes warm and recompiles the rest (see
the map's prototype ticket for measured compile costs).
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("heimdall.capture.npu")

CACHE_SIZE = 6


class NpuInferSession:
    """OpenVINO session compiled for the NPU; recompiles per input shape (LRU)."""

    def __init__(self, cfg: dict[str, Any]):
        import openvino as ov

        self._core = ov.Core()
        model_path = cfg.get("model_path")
        if model_path is None:
            # Mirror OrtInferSession's default-model resolution (#70): rapidocr
            # only sets model_path when the app passed it explicitly (the proto
            # did); otherwise resolve the packaged model via model_root_dir.
            model_path = self._resolve_default_model(cfg)
        self._model_path = Path(model_path)
        self._cache: OrderedDict[tuple, object] = OrderedDict()
        self._in_name = "x"
        self.model = None
        self.session = None

    def _resolve_default_model(self, cfg: dict[str, Any]) -> Path:
        from rapidocr.inference_engine.base import FileInfo, InferSession
        from rapidocr.utils.download_file import DownloadFile, DownloadFileInput

        model_root_dir = cfg.get("model_root_dir")
        if model_root_dir is None:
            raise ValueError("Either model_path or model_root_dir must be provided in the configuration.")
        model_root_dir = Path(model_root_dir)
        model_root_dir.mkdir(parents=True, exist_ok=True)
        model_info = InferSession.get_model_url(
            FileInfo(
                engine_type=cfg.engine_type,
                ocr_version=cfg.ocr_version,
                task_type=cfg.task_type,
                lang_type=cfg.lang_type,
                model_type=cfg.model_type,
            )
        )
        model_path = model_root_dir / Path(model_info["model_dir"]).name
        DownloadFile.run(
            DownloadFileInput(
                file_url=model_info["model_dir"],
                sha256=model_info["SHA256"],
                save_path=model_path,
                logger=logging.getLogger("rapidocr"),
            )
        )
        return model_path

    def _compiled_for(self, input_shape: tuple) -> object:
        import openvino as ov

        key = tuple(input_shape)
        cm = self._cache.get(key)
        if cm is not None:
            self._cache.move_to_end(key)
            return cm
        model = self._core.read_model(self._model_path)
        model.reshape({self._in_name: input_shape})
        cm = self._core.compile_model(model, "NPU")
        self._cache[key] = cm
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return cm

    def __call__(self, input_content: np.ndarray) -> np.ndarray:
        cm = self._compiled_for(input_content.shape)
        req = cm.create_infer_request()
        req.infer({cm.input(0).get_any_name(): input_content})
        return req.get_output_tensor().data

    def get_character_list(self, key: str = "character"):
        model = self._core.read_model(self._model_path)
        rt = model.get_rt_info()
        return rt["framework"][key].value.splitlines()

    def have_key(self, key: str = "character") -> bool:
        try:
            self.get_character_list(key)
            return True
        except Exception:
            return False


def install_npu_engine() -> bool:
    """Point rapidocr's det/cls/rec factories at the NPU session.

    Returns False (and logs) when openvino is missing or no NPU device is
    visible — callers fall back to CPU. Idempotent within a process.
    """
    try:
        import openvino as ov

        core = ov.Core()
        if "NPU" not in core.available_devices:
            log.warning("no NPU device in OpenVINO (%s); OCR engine stays CPU",
                        core.available_devices)
            return False
    except Exception as exc:  # noqa: BLE001
        log.warning("openvino unavailable (%s); OCR engine stays CPU", exc)
        return False

    try:
        import rapidocr.ch_ppocr_cls.main as cls_m
        import rapidocr.ch_ppocr_det.main as det_m
        import rapidocr.ch_ppocr_rec.main as rec_m

        for mod in (det_m, cls_m, rec_m):
            if getattr(mod, "_heimdall_npu_patched", False):
                continue
            _ORIGINALS[mod] = mod.get_engine

            def make(orig=mod.get_engine):
                def get_engine(engine_type):
                    return NpuInferSession

                return get_engine

            mod.get_engine = make()
            mod._heimdall_npu_patched = True
    except Exception as exc:  # noqa: BLE001
        log.warning("rapidocr NPU patch failed (%s); OCR engine stays CPU", exc)
        return False
    log.info("OCR engines routed to NPU (%s)", core.available_devices)
    return True


_ORIGINALS: dict = {}


def uninstall_npu_engine() -> None:
    """Restore rapidocr's original factories (a live npu->cpu flip must not keep
    the NPU route: the patch is process-global, so an explicitly-requested CPU
    engine rebuilds through the untouched factories)."""
    from rapidocr.ch_ppocr_cls import main as cls_m
    from rapidocr.ch_ppocr_det import main as det_m
    from rapidocr.ch_ppocr_rec import main as rec_m

    for mod in (det_m, cls_m, rec_m):
        if not getattr(mod, "_heimdall_npu_patched", False):
            continue
        mod.get_engine = _ORIGINALS.pop(mod, mod.get_engine)
        mod._heimdall_npu_patched = False

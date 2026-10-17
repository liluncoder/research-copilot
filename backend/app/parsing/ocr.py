"""OCR 引擎（CPU）。扫描件分支的实际执行体。

★引擎顺序（2026-10-17 实测后定稿，不许随手改）：
    1. **RapidOCR**（onnxruntime）—— 主力。实测 150dpi 约 46-52 s/页（沙箱限 CPU 环境下），
       比 PaddleOCR(关 mkldnn) 快约 6 倍，识别质量持平（作者/机构/摘要逐字正确）。
    2. **PaddleOCR** —— 兜底。质量最好但 CPU 上慢（同一页 ~295 s），只在 RapidOCR 不可用时启用。
    3. 两者都不可用 ⇒ 抛 OcrUnavailable，**绝不静默返回空串**
       （静默失败会让 J3 假通过 —— 本项目最不能犯的错）。

★2026-10-17 修掉的真 bug：PaddlePaddle 3.3.1 的 oneDNN(MKL-DNN) 后端在
  `ConvertPirAttribute2RuntimeAttribute` 处抛 NotImplementedError
  （`onednn_instruction.cc:118`）。PaddleOCR 必须传 `enable_mkldnn=False` 才能推理。
  代价是慢一个数量级 ⇒ 这就是 RapidOCR 上位的原因。

★性能口径（沙箱限 CPU，非代码问题）：同页 8 线程 48 s vs 16 线程 52 s，无线程加速
  ⇒ 说明是环境限流，不是我们的实现慢。性能数据只记录、不作判据（见 路线/04 §三）。
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


class OcrUnavailable(RuntimeError):
    """OCR 引擎全部不可用。★抛异常而非返回空串：宁可判据失败，不要假通过。"""


class OcrEngine:
    """统一 OCR 入口。实现 pipeline.OcrEngine 的 recognize_page(page, dpi=...) 接口。"""

    def __init__(self, lang: str = "ch", *, prefer: str | None = None):
        self.lang = lang
        self._impl = None
        self._backend: str | None = None
        self._prefer = prefer  # 仅供测试：可强制 "rapid" / "paddle"

    # ---------- 引擎加载（带降级）----------
    def _ensure_loaded(self):
        if self._impl is not None:
            return

        order = ["rapid", "paddle"]
        if self._prefer:
            order = [self._prefer] + [x for x in order if x != self._prefer]

        errors: list[str] = []
        for name in order:
            try:
                if name == "rapid":
                    from rapidocr_onnxruntime import RapidOCR

                    logger.info("初始化 RapidOCR（onnxruntime, cpu）…")
                    self._impl = RapidOCR(intra_op_num_threads=8)
                else:
                    from paddleocr import PaddleOCR

                    logger.info("初始化 PaddleOCR（lang=%s, cpu, mkldnn=off）…", self.lang)
                    self._impl = PaddleOCR(
                        lang=self.lang,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        enable_mkldnn=False,  # ★必须关：3.3.1 oneDNN bug
                    )
                self._backend = name
                return
            except Exception as e:  # noqa: BLE001 - 任何加载失败都要能降级
                logger.warning("%s 不可用（%s），尝试下一个引擎…", name, e)
                errors.append(f"{name}: {e}")

        raise OcrUnavailable("OCR 引擎全部不可用；" + " | ".join(errors))

    @property
    def backend(self) -> str | None:
        return self._backend

    # ---------- 单页识别 ----------
    def recognize_page(self, page, *, dpi: int) -> str:
        """把 PDF 页渲染成图 → OCR → 按行拼接文本。

        ★内存纪律：pixmap 与 numpy 数组用完立刻 del，
        541 页里即使只有少数页面走 OCR，也不能让图像对象累积。
        """
        self._ensure_loaded()

        import pymupdf

        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        img = None
        try:
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            # OCR 引擎要 RGB；PyMuPDF 默认 RGB（n=3）或 RGBA（n=4）
            if pix.n == 4:
                img = img[:, :, :3]
            img = np.ascontiguousarray(img)

            if self._backend == "rapid":
                return self._run_rapid(img)
            return self._run_paddle(img)
        finally:
            del pix
            if img is not None:
                del img

    def _run_rapid(self, img: np.ndarray) -> str:
        # RapidOCR 返回 ([[box, text, score], ...], elapsed)
        result, _ = self._impl(img)
        if not result:
            return ""
        return "\n".join(str(item[1]) for item in result)

    def _run_paddle(self, img: np.ndarray) -> str:
        result = self._impl.predict(img)
        lines: list[str] = []
        for page_res in result:
            try:
                texts = page_res["rec_texts"]
            except (KeyError, TypeError):
                texts = getattr(page_res, "rec_texts", None)
            if texts:
                lines.extend(str(t) for t in texts)
        return "\n".join(lines)


# 向后兼容：旧代码 import PaddleOcrEngine
PaddleOcrEngine = OcrEngine

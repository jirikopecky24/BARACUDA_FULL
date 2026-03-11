from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

import numpy as np

_TORCH_MESHGRID_CACHE: dict[tuple[str, int, int], tuple[object, object]] = {}


class TrackingMethod(str, Enum):
    RADIAL_SYMMETRY = "RADIAL_SYMMETRY"
    INTENSITY_PEAK = "INTENSITY_PEAK"


@dataclass(frozen=True)
class Roi:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Detection:
    x_px: float
    y_px: float
    quality: float
    peak: float


def roi_follow_center(
    frame_shape: tuple[int, int] | tuple[int, int, int],
    roi: Roi,
    center_x_px: float,
    center_y_px: float,
) -> Roi:
    """Return a new ROI with same (w,h) that follows the detected center.

    - Deterministic.
    - Clamped to image bounds.
    - Keeps ROI size constant (audit-friendly + avoids implicit parameter drift).
    """
    H = int(frame_shape[0])
    W = int(frame_shape[1])
    rw = int(max(1, roi.w))
    rh = int(max(1, roi.h))

    # Center -> top-left
    # Use exact same math as auto_roi.py exact center math
    # x = cx - (rw-1)/2.0
    half_w = (rw - 1) / 2.0
    half_h = (rh - 1) / 2.0
    x = int(round(float(center_x_px) - half_w))
    y = int(round(float(center_y_px) - half_h))

    if x < 0:
        x = 0
    if y < 0:
        y = 0
    if x + rw > W:
        x = max(0, W - rw)
    if y + rh > H:
        y = max(0, H - rh)

    return Roi(x=int(x), y=int(y), w=int(rw), h=int(rh))


# ---------------- utils ----------------

def _to_gray_u8(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 2:
        g = arr
    elif arr.ndim == 3 and arr.shape[2] >= 3:
        r = arr[..., 0].astype(np.float32)
        gch = arr[..., 1].astype(np.float32)
        b = arr[..., 2].astype(np.float32)
        g = 0.299 * r + 0.587 * gch + 0.114 * b
    else:
        raise ValueError(f"Unsupported image shape: {arr.shape}")

    if g.dtype != np.uint8:
        g = np.clip(g, 0, 255).astype(np.uint8)
    return g


def _clip_roi(gray: np.ndarray, roi: Optional[Roi]) -> Tuple[np.ndarray, Tuple[int, int]]:
    H, W = gray.shape
    if roi is None:
        return gray, (0, 0)

    x = int(max(0, min(W - 1, roi.x)))
    y = int(max(0, min(H - 1, roi.y)))
    w = int(max(1, min(W - x, roi.w)))
    h = int(max(1, min(H - y, roi.h)))

    return gray[y: y + h, x: x + w], (x, y)


def _gaussian_blur_u8(gray_u8: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return gray_u8.astype(np.float32)

    try:
        import cv2
        blurred = cv2.GaussianBlur(gray_u8, ksize=(0, 0), sigmaX=float(sigma), sigmaY=float(sigma))
        return blurred.astype(np.float32)
    except Exception:
        # fallback: separable box blur (deterministic)
        k = int(max(3, round(sigma * 3) * 2 + 1))
        arr = gray_u8.astype(np.float32)
        kernel = np.ones((k,), dtype=np.float32) / float(k)
        arr = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="same"), 0, arr)
        arr = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="same"), 1, arr)
        return arr


def _subpixel_quadratic_1d(v_m1: float, v_0: float, v_p1: float) -> float:
    denom = (v_m1 - 2.0 * v_0 + v_p1)
    if abs(denom) < 1e-12:
        return 0.0
    return 0.5 * (v_m1 - v_p1) / denom


def _central_gradients(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    f = img.astype(np.float32, copy=False)

    gx = np.zeros_like(f, dtype=np.float32)
    gy = np.zeros_like(f, dtype=np.float32)

    gx[:, 1:-1] = 0.5 * (f[:, 2:] - f[:, :-2])
    gx[:, 0] = f[:, 1] - f[:, 0]
    gx[:, -1] = f[:, -1] - f[:, -2]

    gy[1:-1, :] = 0.5 * (f[2:, :] - f[:-2, :])
    gy[0, :] = f[1, :] - f[0, :]
    gy[-1, :] = f[-1, :] - f[-2, :]

    return gx, gy


def _smooth_1d(x: np.ndarray, k: int) -> np.ndarray:
    k = int(max(1, k))
    if k == 1:
        return x.astype(np.float64)
    if k % 2 == 0:
        k += 1
    kernel = np.ones((k,), dtype=np.float64) / float(k)
    return np.convolve(x.astype(np.float64), kernel, mode="same").astype(np.float64)


# ---------------- INTENSITY PEAK (fallback) ----------------

def detect_intensity_peak(
    image: np.ndarray,
    roi: Optional[Roi],
    invert: bool = True,
    blur_sigma: float = 1.2,
) -> Detection:
    gray = _to_gray_u8(image)
    roi_img, (ox, oy) = _clip_roi(gray, roi)

    resp_u8 = (255 - roi_img).astype(np.uint8) if invert else roi_img
    resp = _gaussian_blur_u8(resp_u8, sigma=blur_sigma)

    h, w = resp.shape
    if h < 3 or w < 3:
        yy, xx = np.unravel_index(int(np.argmax(resp)), resp.shape)
        x = float(ox + xx)
        y = float(oy + yy)
        mu = float(resp.mean())
        sd = float(resp.std() + 1e-9)
        peak = float(resp[yy, xx])
        q = (peak - mu) / sd
        return Detection(x_px=x, y_px=y, quality=float(q), peak=float(peak))

    yy, xx = np.unravel_index(int(np.argmax(resp)), resp.shape)
    yy0 = int(max(1, min(h - 2, yy)))
    xx0 = int(max(1, min(w - 2, xx)))

    dx = _subpixel_quadratic_1d(resp[yy0, xx0 - 1], resp[yy0, xx0], resp[yy0, xx0 + 1])
    dy = _subpixel_quadratic_1d(resp[yy0 - 1, xx0], resp[yy0, xx0], resp[yy0 + 1, xx0])

    x = float(ox + xx0) + float(dx)
    y = float(oy + yy0) + float(dy)

    mu = float(resp.mean())
    sd = float(resp.std() + 1e-9)
    peak = float(resp[yy0, xx0])
    q = (peak - mu) / sd
    return Detection(x_px=x, y_px=y, quality=float(q), peak=float(peak))


# ---------------- RADIAL SYMMETRY (Nature-grade) ----------------

def _solve_rs_center_from_gradients(
    gx: np.ndarray,
    gy: np.ndarray,
    gmag: np.ndarray,
    radial_grad_threshold: float,
    annulus_r_inner: float | None,
    annulus_r_outer: float | None,
    center_hint_xy: tuple[float, float] | None,
) -> tuple[float, float, float, float]:
    h, w = gmag.shape
    mask = gmag >= float(radial_grad_threshold)

    if center_hint_xy is not None and annulus_r_inner is not None and annulus_r_outer is not None:
        cxh, cyh = float(center_hint_xy[0]), float(center_hint_xy[1])
        yy, xx = np.mgrid[0:h, 0:w]
        rr = np.sqrt((xx - cxh) ** 2 + (yy - cyh) ** 2)
        mask = mask & (rr >= float(annulus_r_inner)) & (rr <= float(annulus_r_outer))

    if not np.any(mask):
        return np.nan, np.nan, 0.0, 0.0

    eps = 1e-12
    inv = 1.0 / (gmag + eps)
    nx = gx * inv
    ny = gy * inv

    wm = (gmag[mask].astype(np.float64) ** 2)

    yy, xx = np.mgrid[0:h, 0:w]
    xxm = xx[mask].astype(np.float64)
    yym = yy[mask].astype(np.float64)
    nxm = nx[mask].astype(np.float64)
    nym = ny[mask].astype(np.float64)

    a11 = np.sum(wm * (1.0 - nxm * nxm))
    a12 = np.sum(wm * (-nxm * nym))
    a22 = np.sum(wm * (1.0 - nym * nym))

    b1 = np.sum(wm * ((1.0 - nxm * nxm) * xxm + (-nxm * nym) * yym))
    b2 = np.sum(wm * ((-nxm * nym) * xxm + (1.0 - nym * nym) * yym))

    A = np.array([[a11, a12], [a12, a22]], dtype=np.float64)
    b = np.array([b1, b2], dtype=np.float64)

    detA = float(np.linalg.det(A))
    if abs(detA) < 1e-12:
        return np.nan, np.nan, 0.0, 0.0

    c = np.linalg.solve(A, b)
    cx = float(np.clip(c[0], 0.0, float(w - 1)))
    cy = float(np.clip(c[1], 0.0, float(h - 1)))

    dx = cx - xxm
    dy = cy - yym
    ndotv = nxm * dx + nym * dy
    rx = dx - nxm * ndotv
    ry = dy - nym * ndotv

    r = np.sum(wm * (rx * rx + ry * ry)) + 1e-9
    wsum = float(np.sum(wm) + 1e-12)

    rr = np.sqrt(dx * dx + dy * dy) + 1e-12
    ux = dx / rr
    uy = dy / rr
    cos_abs = np.abs(nxm * ux + nym * uy)
    inlier = cos_abs >= 0.7
    inlier_ratio = float(np.sum(inlier)) / float(len(cos_abs) + 1e-12)

    quality = float((wsum / r) * (0.25 + 0.75 * inlier_ratio))

    ix = int(round(cx))
    iy = int(round(cy))
    ix = max(0, min(w - 1, ix))
    iy = max(0, min(h - 1, iy))
    peak = float(gmag[iy, ix])  # polarity-invariant

    return cx, cy, quality, peak


def _estimate_annulus_from_gradient_profile(
    gmag: np.ndarray,
    center_xy: tuple[float, float],
    smooth_k: int = 3,
) -> tuple[float, float]:
    h, w = gmag.shape
    cx, cy = float(center_xy[0]), float(center_xy[1])

    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    rmax = int(np.floor(min(h, w) * 0.5))
    rmax = max(5, min(rmax, int(np.max(rr))))

    r_int = np.clip(rr.astype(np.int32), 0, rmax)
    prof_sum = np.bincount(r_int.ravel(), weights=gmag.ravel().astype(np.float64), minlength=rmax + 1)
    prof_cnt = np.bincount(r_int.ravel(), minlength=rmax + 1).astype(np.float64)
    prof = prof_sum / np.maximum(1.0, prof_cnt)

    prof = _smooth_1d(prof, smooth_k)

    r0 = 3
    r1 = rmax
    if r1 <= r0 + 3:
        return 2.0, float(rmax)

    peak_r = int(np.argmax(prof[r0:r1]) + r0)
    peak_r = max(3, min(rmax, peak_r))

    r_inner = 0.60 * float(peak_r)
    r_outer = 1.40 * float(peak_r)

    r_inner = float(np.clip(r_inner, 2.0, float(rmax - 2)))
    r_outer = float(np.clip(r_outer, r_inner + 2.0, float(rmax)))

    return r_inner, r_outer


def _detect_radial_symmetry_cpu_from_work(
    image: np.ndarray,
    roi: Optional[Roi],
    work: np.ndarray,
    ox: int,
    oy: int,
    invert: bool,
    blur_sigma: float,
    radial_grad_threshold: float,
    annulus_r_inner_px: float | None,
    annulus_r_outer_px: float | None,
    annulus_auto: bool,
    annulus_profile_smooth: int,
) -> Detection:
    gx, gy = _central_gradients(work)
    gmag = np.sqrt(gx * gx + gy * gy).astype(np.float32)

    h, w = gmag.shape
    if h < 3 or w < 3:
        return detect_intensity_peak(image, roi, invert=invert, blur_sigma=blur_sigma)

    cx0, cy0, q0, peak0 = _solve_rs_center_from_gradients(
        gx, gy, gmag,
        radial_grad_threshold=radial_grad_threshold,
        annulus_r_inner=None,
        annulus_r_outer=None,
        center_hint_xy=None,
    )
    if not np.isfinite(cx0) or not np.isfinite(cy0) or q0 <= 0:
        return detect_intensity_peak(image, roi, invert=invert, blur_sigma=blur_sigma)

    r_in = annulus_r_inner_px
    r_out = annulus_r_outer_px
    if annulus_auto or (r_in is None or r_out is None):
        r_in_est, r_out_est = _estimate_annulus_from_gradient_profile(
            gmag, center_xy=(cx0, cy0), smooth_k=int(annulus_profile_smooth)
        )
        if r_in is None:
            r_in = r_in_est
        if r_out is None:
            r_out = r_out_est

    cx1, cy1, q1, peak1 = _solve_rs_center_from_gradients(
        gx, gy, gmag,
        radial_grad_threshold=radial_grad_threshold,
        annulus_r_inner=float(r_in) if r_in is not None else None,
        annulus_r_outer=float(r_out) if r_out is not None else None,
        center_hint_xy=(cx0, cy0),
    )

    if np.isfinite(cx1) and np.isfinite(cy1) and q1 > 0:
        cx, cy, quality, peak = cx1, cy1, q1, peak1
    else:
        cx, cy, quality, peak = cx0, cy0, q0, peak0

    x = float(ox) + float(cx)
    y = float(oy) + float(cy)
    return Detection(x_px=x, y_px=y, quality=float(quality), peak=float(peak))


def _to_cuda_tensor(work: np.ndarray):
    import torch

    return torch.as_tensor(work, device="cuda", dtype=torch.float32)


def _smooth_1d_torch(x, k: int):
    import torch

    k = int(max(1, k))
    if k == 1:
        return x.to(torch.float32)
    if k % 2 == 0:
        k += 1
    kernel = torch.ones((1, 1, k), device=x.device, dtype=torch.float32) / float(k)
    src = x.to(torch.float32).view(1, 1, -1)
    pad = k // 2
    src = torch.nn.functional.pad(src, (pad, pad), mode="replicate")
    return torch.nn.functional.conv1d(src, kernel).view(-1)


def _get_torch_meshgrid(device, h: int, w: int):
    import torch

    key = (str(device), int(h), int(w))
    cached = _TORCH_MESHGRID_CACHE.get(key)
    if cached is not None:
        return cached
    yy, xx = torch.meshgrid(
        torch.arange(h, device=device, dtype=torch.float32),
        torch.arange(w, device=device, dtype=torch.float32),
        indexing="ij",
    )
    _TORCH_MESHGRID_CACHE[key] = (yy, xx)
    return yy, xx


def _solve_rs_center_from_gradients_torch(
    gx,
    gy,
    gmag,
    radial_grad_threshold: float,
    annulus_r_inner: float | None,
    annulus_r_outer: float | None,
    center_hint_xy: tuple[float, float] | None,
) -> tuple[float, float, float, float]:
    import torch

    h, w = gmag.shape
    mask = gmag >= float(radial_grad_threshold)

    yy, xx = _get_torch_meshgrid(gmag.device, h, w)

    if center_hint_xy is not None and annulus_r_inner is not None and annulus_r_outer is not None:
        cxh, cyh = float(center_hint_xy[0]), float(center_hint_xy[1])
        rr = torch.sqrt((xx - cxh) ** 2 + (yy - cyh) ** 2)
        mask = mask & (rr >= float(annulus_r_inner)) & (rr <= float(annulus_r_outer))

    if int(mask.count_nonzero().item()) == 0:
        return np.nan, np.nan, 0.0, 0.0

    eps = 1e-12
    inv = 1.0 / (gmag + eps)
    nx = gx * inv
    ny = gy * inv

    wm = gmag[mask].to(torch.float32) ** 2
    xxm = xx[mask].to(torch.float32)
    yym = yy[mask].to(torch.float32)
    nxm = nx[mask].to(torch.float32)
    nym = ny[mask].to(torch.float32)

    a11 = torch.sum(wm * (1.0 - nxm * nxm))
    a12 = torch.sum(wm * (-nxm * nym))
    a22 = torch.sum(wm * (1.0 - nym * nym))

    b1 = torch.sum(wm * ((1.0 - nxm * nxm) * xxm + (-nxm * nym) * yym))
    b2 = torch.sum(wm * ((-nxm * nym) * xxm + (1.0 - nym * nym) * yym))

    detA = a11 * a22 - a12 * a12
    if bool((torch.abs(detA) < 1e-12).item()):
        return np.nan, np.nan, 0.0, 0.0

    inv_det = 1.0 / detA
    cx_t = torch.clamp((a22 * b1 - a12 * b2) * inv_det, 0.0, float(w - 1))
    cy_t = torch.clamp((a11 * b2 - a12 * b1) * inv_det, 0.0, float(h - 1))

    dx = cx_t - xxm
    dy = cy_t - yym
    ndotv = nxm * dx + nym * dy
    rx = dx - nxm * ndotv
    ry = dy - nym * ndotv

    r_t = torch.sum(wm * (rx * rx + ry * ry)) + 1e-9
    wsum_t = torch.sum(wm) + 1e-12

    rr = torch.sqrt(dx * dx + dy * dy) + 1e-12
    ux = dx / rr
    uy = dy / rr
    cos_abs = torch.abs(nxm * ux + nym * uy)
    inlier = cos_abs >= 0.7
    inlier_ratio_t = torch.sum(inlier.to(torch.float32)) / float(cos_abs.numel() + 1e-12)

    quality_t = (wsum_t / r_t) * (0.25 + 0.75 * inlier_ratio_t)

    ix_t = torch.clamp(torch.round(cx_t).to(torch.int64), 0, w - 1)
    iy_t = torch.clamp(torch.round(cy_t).to(torch.int64), 0, h - 1)
    peak_t = gmag[iy_t, ix_t]
    out = torch.stack([cx_t, cy_t, quality_t, peak_t]).detach().cpu().tolist()
    return float(out[0]), float(out[1]), float(out[2]), float(out[3])


def _estimate_annulus_from_gradient_profile_torch(
    gmag,
    center_xy: tuple[float, float],
    smooth_k: int = 3,
) -> tuple[float, float]:
    import torch

    h, w = gmag.shape
    cx, cy = float(center_xy[0]), float(center_xy[1])
    yy, xx = _get_torch_meshgrid(gmag.device, h, w)
    rr = torch.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    rmax = int(np.floor(min(h, w) * 0.5))
    rmax = max(5, min(rmax, int(torch.max(rr).item())))

    r_int = torch.clamp(rr.to(torch.int64), 0, rmax)
    prof_sum = torch.bincount(r_int.reshape(-1), weights=gmag.reshape(-1).to(torch.float32), minlength=rmax + 1)
    prof_cnt = torch.bincount(r_int.reshape(-1), minlength=rmax + 1).to(torch.float32)
    prof = prof_sum / torch.clamp(prof_cnt, min=1.0)
    prof = _smooth_1d_torch(prof, smooth_k)

    r0 = 3
    r1 = rmax
    if r1 <= r0 + 3:
        return 2.0, float(rmax)

    peak_r = int(torch.argmax(prof[r0:r1]).item()) + r0
    peak_r = max(3, min(rmax, peak_r))

    r_inner = float(np.clip(0.60 * float(peak_r), 2.0, float(rmax - 2)))
    r_outer = float(np.clip(1.40 * float(peak_r), r_inner + 2.0, float(rmax)))
    return r_inner, r_outer


def _detect_radial_symmetry_cuda_from_work(
    image: np.ndarray,
    roi: Optional[Roi],
    work: np.ndarray,
    ox: int,
    oy: int,
    invert: bool,
    blur_sigma: float,
    radial_grad_threshold: float,
    annulus_r_inner_px: float | None,
    annulus_r_outer_px: float | None,
    annulus_auto: bool,
    annulus_profile_smooth: int,
) -> Detection:
    import torch

    h, w = work.shape
    if h < 3 or w < 3:
        return detect_intensity_peak(image, roi, invert=invert, blur_sigma=blur_sigma)

    work_t = _to_cuda_tensor(work)
    gx = torch.zeros_like(work_t, dtype=torch.float32)
    gy = torch.zeros_like(work_t, dtype=torch.float32)

    gx[:, 1:-1] = 0.5 * (work_t[:, 2:] - work_t[:, :-2])
    gx[:, 0] = work_t[:, 1] - work_t[:, 0]
    gx[:, -1] = work_t[:, -1] - work_t[:, -2]

    gy[1:-1, :] = 0.5 * (work_t[2:, :] - work_t[:-2, :])
    gy[0, :] = work_t[1, :] - work_t[0, :]
    gy[-1, :] = work_t[-1, :] - work_t[-2, :]

    gmag = torch.sqrt(gx * gx + gy * gy).to(torch.float32)

    cx0, cy0, q0, peak0 = _solve_rs_center_from_gradients_torch(
        gx, gy, gmag,
        radial_grad_threshold=radial_grad_threshold,
        annulus_r_inner=None,
        annulus_r_outer=None,
        center_hint_xy=None,
    )
    if not np.isfinite(cx0) or not np.isfinite(cy0) or q0 <= 0:
        return detect_intensity_peak(image, roi, invert=invert, blur_sigma=blur_sigma)

    r_in = annulus_r_inner_px
    r_out = annulus_r_outer_px
    if annulus_auto or (r_in is None or r_out is None):
        r_in_est, r_out_est = _estimate_annulus_from_gradient_profile_torch(
            gmag, center_xy=(cx0, cy0), smooth_k=int(annulus_profile_smooth)
        )
        if r_in is None:
            r_in = r_in_est
        if r_out is None:
            r_out = r_out_est

    cx1, cy1, q1, peak1 = _solve_rs_center_from_gradients_torch(
        gx, gy, gmag,
        radial_grad_threshold=radial_grad_threshold,
        annulus_r_inner=float(r_in) if r_in is not None else None,
        annulus_r_outer=float(r_out) if r_out is not None else None,
        center_hint_xy=(cx0, cy0),
    )

    if np.isfinite(cx1) and np.isfinite(cy1) and q1 > 0:
        cx, cy, quality, peak = cx1, cy1, q1, peak1
    else:
        cx, cy, quality, peak = cx0, cy0, q0, peak0

    x = float(ox) + float(cx)
    y = float(oy) + float(cy)
    return Detection(x_px=x, y_px=y, quality=float(quality), peak=float(peak))


def detect_radial_symmetry(
    image: np.ndarray,
    roi: Optional[Roi],
    invert: bool = True,
    blur_sigma: float = 1.2,
    radial_grad_threshold: float = 2.0,
    annulus_r_inner_px: float | None = None,
    annulus_r_outer_px: float | None = None,
    annulus_auto: bool = True,
    annulus_profile_smooth: int = 3,
    compute_device: str = "cpu",
) -> Detection:
    gray = _to_gray_u8(image)
    roi_u8, (ox, oy) = _clip_roi(gray, roi)

    work_u8 = (255 - roi_u8).astype(np.uint8) if invert else roi_u8
    work = _gaussian_blur_u8(work_u8, sigma=blur_sigma)
    if str(compute_device).strip().lower() == "cuda":
        try:
            return _detect_radial_symmetry_cuda_from_work(
                image=image,
                roi=roi,
                work=work,
                ox=ox,
                oy=oy,
                invert=invert,
                blur_sigma=blur_sigma,
                radial_grad_threshold=radial_grad_threshold,
                annulus_r_inner_px=annulus_r_inner_px,
                annulus_r_outer_px=annulus_r_outer_px,
                annulus_auto=annulus_auto,
                annulus_profile_smooth=annulus_profile_smooth,
            )
        except Exception:
            pass

    return _detect_radial_symmetry_cpu_from_work(
        image=image,
        roi=roi,
        work=work,
        ox=ox,
        oy=oy,
        invert=invert,
        blur_sigma=blur_sigma,
        radial_grad_threshold=radial_grad_threshold,
        annulus_r_inner_px=annulus_r_inner_px,
        annulus_r_outer_px=annulus_r_outer_px,
        annulus_auto=annulus_auto,
        annulus_profile_smooth=annulus_profile_smooth,
    )


def track_particle(
    image: np.ndarray,
    roi: Optional[Roi],
    method: TrackingMethod = TrackingMethod.RADIAL_SYMMETRY,
    invert: bool = True,
    blur_sigma: float = 1.2,
    radial_grad_threshold: float = 2.0,
    auto_polarity: bool = True,
    annulus_r_inner_px: float | None = None,
    annulus_r_outer_px: float | None = None,
    annulus_auto: bool = True,
    annulus_profile_smooth: int = 3,
    compute_device: str = "cpu",
) -> Detection:
    def _run(invert_flag: bool) -> Detection:
        if method == TrackingMethod.INTENSITY_PEAK:
            return detect_intensity_peak(image, roi, invert=invert_flag, blur_sigma=blur_sigma)
        return detect_radial_symmetry(
            image,
            roi,
            invert=invert_flag,
            blur_sigma=blur_sigma,
            radial_grad_threshold=radial_grad_threshold,
            annulus_r_inner_px=annulus_r_inner_px,
            annulus_r_outer_px=annulus_r_outer_px,
            annulus_auto=annulus_auto,
            annulus_profile_smooth=annulus_profile_smooth,
            compute_device=compute_device,
        )

    if not auto_polarity:
        return _run(bool(invert))

    d1 = _run(True)
    d2 = _run(False)
    return d1 if d1.quality >= d2.quality else d2

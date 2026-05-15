"""Umi-OCR 集成模块 — 自动发现 + 自动启动 + 工具注册"""

import os
from pathlib import Path

UMI_OCR_BASE = "http://127.0.0.1:1224"
_umi_process = None


def _find_umi_ocr_exe() -> str:
    candidates = [
        Path(__file__).parent.parent.parent.parent / "Umi-OCR_Paddle_v2.1.5" / "Umi-OCR.exe",
        Path(__file__).parent.parent.parent / "Umi-OCR_Paddle_v2.1.5" / "Umi-OCR.exe",
        Path(os.environ.get("UMI_OCR_PATH", "")) if os.environ.get("UMI_OCR_PATH") else None,
    ]
    for drive in ["C", "D", "E", "F"]:
        candidates.append(Path(f"{drive}:/Umi-OCR_Paddle_v2.1.5/Umi-OCR.exe"))
        candidates.append(Path(f"{drive}:/AI产品/Umi-OCR_Paddle_v2.1.5/Umi-OCR.exe"))
        candidates.append(Path(f"{drive}:/Program Files/Umi-OCR/Umi-OCR.exe"))
    for p in candidates:
        if p and p.exists():
            return str(p)
    return ""


def _is_umi_running() -> bool:
    import requests
    try:
        requests.get(f"{UMI_OCR_BASE}/api/ocr/get_options", timeout=2)
        return True
    except Exception:
        return False


def _ensure_umi_ocr() -> dict:
    global _umi_process
    import subprocess, time

    if _is_umi_running():
        return {"ok": True}

    exe = _find_umi_ocr_exe()
    if not exe:
        return {"error": "未找到 Umi-OCR，请设置环境变量 UMI_OCR_PATH 或将 Umi-OCR 放在常见位置"}

    try:
        _umi_process = subprocess.Popen(
            [exe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        return {"error": f"启动 Umi-OCR 失败: {e}"}

    for _ in range(30):
        time.sleep(1)
        if _is_umi_running():
            return {"ok": True, "auto_started": True, "exe": exe}

    return {"error": f"Umi-OCR 启动超时 (30s)，路径: {exe}"}


def ocr_base64(img_b64: str, options: dict = None) -> dict:
    import requests

    status = _ensure_umi_ocr()
    if "error" in status:
        return status

    payload = {"base64": img_b64, "options": options or {"data.format": "text"}}
    try:
        resp = requests.post(f"{UMI_OCR_BASE}/api/ocr", json=payload, timeout=30)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}"}
        result = resp.json()
        code = result.get("code", -1)
        if code == 100:
            return {"success": True, "text": result.get("data", ""), "code": 100}
        if code == 101:
            return {"success": True, "text": "", "code": 101, "message": "图片中无文字"}
        return {"error": f"OCR返回异常: {result}"}
    except requests.exceptions.Timeout:
        return {"error": "OCR 超时"}
    except Exception as e:
        return {"error": str(e)}


# ============== Tool handlers ==============

def ocr_image_handler(args: dict) -> dict:
    import base64

    image_path = args.get("image_path", "")
    if not image_path:
        return {"error": "未提供图片路径"}

    img = Path(image_path)
    if not img.exists():
        return {"error": f"图片不存在: {image_path}"}

    with open(img, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
    return ocr_base64(img_b64)


def ocr_url_handler(args: dict) -> dict:
    import requests, base64

    url = args.get("url", "")
    if not url:
        return {"error": "未提供图片URL"}

    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return {"error": f"下载失败: HTTP {resp.status_code}"}
        img_b64 = base64.b64encode(resp.content).decode("utf-8")
        return ocr_base64(img_b64)
    except Exception as e:
        return {"error": f"下载图片失败: {e}"}


def ocr_batch_handler(args: dict) -> dict:
    import base64

    paths = args.get("image_paths", [])
    folder = args.get("folder", "")

    if folder:
        p = Path(folder)
        if p.is_dir():
            paths = [str(f) for f in p.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")]

    if not paths:
        return {"error": "未找到图片"}

    status = _ensure_umi_ocr()
    if "error" in status:
        return status

    results = []
    for path in paths:
        img = Path(path)
        if not img.exists():
            results.append({"file": path, "error": "文件不存在"})
            continue
        with open(img, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        r = ocr_base64(img_b64)
        r["file"] = img.name
        results.append(r)

    total = len(results)
    success = sum(1 for r in results if r.get("success"))
    return {"success": True, "total": total, "recognized": success, "results": results}


def ocr_status_handler(args: dict) -> dict:
    auto_start = args.get("auto_start", False)

    if _is_umi_running():
        import requests
        resp = requests.get(f"{UMI_OCR_BASE}/api/ocr/get_options", timeout=5)
        opts = resp.json()
        lang = opts.get("ocr.language", {}).get("default", "unknown")
        return {"success": True, "status": "running", "language": lang, "api": UMI_OCR_BASE}

    exe = _find_umi_ocr_exe()
    info = {"success": True, "status": "offline", "exe_found": bool(exe), "exe_path": exe}

    if auto_start and exe:
        result = _ensure_umi_ocr()
        if result.get("ok"):
            info["status"] = "started"
            info["message"] = "已自动启动 Umi-OCR"
        else:
            info["error"] = result.get("error", "启动失败")
    elif not exe:
        info["message"] = "未找到 Umi-OCR，请安装或设置 UMI_OCR_PATH 环境变量"
    else:
        info["message"] = f"Umi-OCR 未运行，可自动启动 ({exe})"
    return info


# ============== Registration ==============

def register_ocr_tools(registry):
    registry.register(
        name="ocr_image", toolset="ocr",
        schema={"type": "object", "properties": {"image_path": {"type": "string", "description": "本地图片文件路径"}}, "required": ["image_path"]},
        handler=ocr_image_handler,
        description="识别本地图片中的文字 (Umi-OCR)", emoji="📝",
    )
    registry.register(
        name="ocr_url", toolset="ocr",
        schema={"type": "object", "properties": {"url": {"type": "string", "description": "图片URL地址"}}, "required": ["url"]},
        handler=ocr_url_handler,
        description="下载网络图片并识别文字 (Umi-OCR)", emoji="🔗",
    )
    registry.register(
        name="ocr_batch", toolset="ocr",
        schema={"type": "object", "properties": {
            "image_paths": {"type": "array", "items": {"type": "string"}, "description": "图片路径列表"},
            "folder": {"type": "string", "description": "图片文件夹路径（自动扫描图片）"},
        }},
        handler=ocr_batch_handler,
        description="批量识别多张图片中的文字 (Umi-OCR)", emoji="📑",
    )
    registry.register(
        name="ocr_status", toolset="ocr",
        schema={"type": "object", "properties": {"auto_start": {"type": "boolean", "description": "是否自动启动 Umi-OCR（默认 false）"}}},
        handler=ocr_status_handler,
        description="检查 Umi-OCR 服务是否在线", emoji="🔍",
    )

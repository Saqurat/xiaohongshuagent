"""
routes_xhs_service.py
管理小红书 MCP 进程的生命周期：启动、停止、状态查询。

  POST /xhs-service/start   启动 xiaohongshu-mcp 二进制
  POST /xhs-service/stop    停止进程
  GET  /xhs-service/status  查询运行状态
"""

import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/xhs-service", tags=["XHS Service"])

# 全局进程句柄
_proc: Optional[subprocess.Popen] = None


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """检查端口是否在监听。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_running() -> bool:
    """进程存活 且 端口可达 → 认为服务正在运行。"""
    global _proc
    if _proc is not None and _proc.poll() is None:
        return True
    # 即使不是本进程启动，也检测端口
    return _port_open("127.0.0.1", 18060)


@router.get("/status", summary="查询 MCP 服务运行状态")
def get_status() -> dict:
    return {
        "running": _is_running(),
        "port": 18060,
        "binary": settings.xhs_mcp_binary,
    }


@router.post("/start", summary="启动 MCP 服务")
def start_service(headless: bool = True) -> dict:
    global _proc

    if _is_running():
        return {"success": True, "message": "服务已在运行", "running": True}

    binary = settings.xhs_mcp_binary
    if not binary:
        return {"success": False, "message": "未配置 XHS_MCP_BINARY 路径", "running": False}

    try:
        args = [binary]
        if not headless:
            args.append("-headless=false")

        # 在二进制所在目录启动，确保 cookies.json 路径正确
        cwd = str(Path(binary).parent)

        # Windows 下用 CREATE_NEW_CONSOLE 让浏览器窗口独立弹出
        kwargs: dict = {"cwd": cwd}
        if sys.platform == "win32" and not headless:
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

        _proc = subprocess.Popen(args, **kwargs)

        # 等待最多 8 秒让端口就绪
        for _ in range(16):
            import time
            time.sleep(0.5)
            if _port_open("127.0.0.1", 18060):
                return {"success": True, "message": "MCP 服务已启动", "running": True}

        return {"success": False, "message": "进程已启动但端口未就绪，请稍后重试", "running": False}

    except FileNotFoundError:
        return {"success": False, "message": f"找不到二进制文件: {binary}", "running": False}
    except Exception as e:
        return {"success": False, "message": f"启动失败: {e}", "running": False}


@router.post("/login", summary="运行登录工具（弹出浏览器扫码）")
def run_login() -> dict:
    binary = settings.xhs_mcp_binary
    if not binary:
        return {"success": False, "message": "未配置 XHS_MCP_BINARY 路径"}

    # 登录二进制与 MCP 二进制同目录，只是文件名不同
    binary_dir = Path(binary).parent
    login_candidates = list(binary_dir.glob("*login*"))
    if not login_candidates:
        return {"success": False, "message": f"未找到登录工具（在 {binary_dir} 搜索 *login*）"}

    login_bin = str(login_candidates[0])
    try:
        kwargs: dict = {"cwd": str(binary_dir)}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        subprocess.Popen([login_bin], **kwargs)
        return {"success": True, "message": f"已启动登录工具，请在弹出的浏览器中扫码登录", "binary": login_bin}
    except Exception as e:
        return {"success": False, "message": f"启动登录工具失败: {e}"}


@router.post("/stop", summary="停止 MCP 服务")
def stop_service() -> dict:
    global _proc

    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
        _proc = None
        return {"success": True, "message": "服务已停止", "running": False}

    return {"success": True, "message": "服务未运行", "running": False}

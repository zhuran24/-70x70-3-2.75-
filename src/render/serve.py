"""Web 查看器本地服务脚本。"""
import http.server
import socketserver
import webbrowser
import shutil
import json
from pathlib import Path


def serve_viewer(port: int = 8070, project_root: Optional[Path] = None):
    """启动本地 HTTP 服务器展示交互式查看器。"""
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent.parent

    viewer_dir = Path(__file__).parent / "web_viewer"
    solution_path = project_root / "data" / "solutions" / "final_solution.json"
    pools_path = project_root / "data" / "preprocessed" / "candidate_placements.json"

    # 复制数据文件到 viewer 目录
    if solution_path.exists():
        shutil.copy2(solution_path, viewer_dir / "final_solution.json")
    if pools_path.exists():
        shutil.copy2(pools_path, viewer_dir / "candidate_placements.json")

    print(f"\n🌐 [VIS-04] 启动交互式查看器")
    print(f"   打开浏览器: http://localhost:{port}")
    print(f"   按 Ctrl+C 停止\n")

    import os
    os.chdir(str(viewer_dir))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        webbrowser.open(f"http://localhost:{port}")
        httpd.serve_forever()


from typing import Optional

if __name__ == "__main__":
    serve_viewer()

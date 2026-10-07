"""
webapis: deal_files 的 FastAPI 封装层

所有 deal_files 能力复用 AIchat.deal_files（单一真相源）。

FastAPI 应用（在项目根目录执行）：
  from total_file.webapis.app import app
  uvicorn total_file.webapis.app:app --host 0.0.0.0 --port 8000
"""

# Speech to Text Service

一个运行在本机的异步转写服务，封装你本地的 Qwen3-ASR OpenAI-compatible 接口。

> Disclaimer
>
> This project was built with substantial AI assistance. The repository owner is not a professional software engineer, so the implementation may still contain rough edges, incorrect assumptions, or places that need further review before production use.

项目当前只负责“转写层”：

- 接收本地音频 / 视频文件
- 视频抽音频
- 调用本地 Qwen3-ASR 转写
- 自动切片处理长音频
- 输出 `json / srt / txt`
- 记录转写耗时等指标

项目当前不负责：

- 视频下载
- 摘要 / 详细报告生成
- 知识库同步

## Features

- FastAPI HTTP API
- 本地 CLI 调用
- SQLite 任务存储
- 异步任务轮询
- 长音频自动切片 + 重叠拼接
- Qwen3-ASR 输出前缀基础清洗
- Windows 后台静默启动脚本

## Project Structure

```text
app/
  api/         HTTP API
  db/          SQLite repository
  models/      Pydantic schemas
  services/    ASR / media / storage services
  workers/     Background job runner
scripts/       Windows start/stop scripts
tests/         Pytest tests
data/jobs/     Per-job outputs
logs/          Background service logs
```

## Requirements

- Python 3.11+
- 已运行的 Qwen3-ASR OpenAI-compatible 服务
- `ffmpeg`

## Environment

复制环境变量模板：

```powershell
copy .env.example .env
```

关键配置项：

```env
ASR_BASE_URL=http://127.0.0.1:8000/v1
ASR_API_KEY=
ASR_MODEL=Qwen3-ASR-0.6B
DATABASE_URL=sqlite:///data/app.db
JOBS_DIR=data/jobs
FFMPEG_PATH=ffmpeg
MAX_UPLOAD_SIZE_MB=500
ASR_MAX_FILE_SIZE_MB=25
CHUNK_DURATION_SECONDS=50
CHUNK_OVERLAP_SECONDS=5
WORKER_POLL_INTERVAL_SECONDS=1.0
SERVICE_BASE_URL=http://127.0.0.1:8010
```

说明：

- `ASR_BASE_URL` 指向你本地 Qwen3-ASR 服务
- `ASR_MAX_FILE_SIZE_MB` 是上游 ASR 单次安全阈值，超过后本项目会自动切片
- `SERVICE_BASE_URL` 是 CLI 访问本地服务时使用的地址

## Install

```powershell
pip install -e .[dev]
```

## Run

前台启动：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### Background Service (Windows)

后台静默启动，不弹新窗口：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_service.ps1
```

停止后台服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_service.ps1
```

日志位置：

- `logs/service.out.log`
- `logs/service.err.log`

## HTTP API

### 1. Submit Transcription Job

```powershell
curl.exe -X POST "http://127.0.0.1:8010/jobs/transcriptions" `
  -F "file=@D:\path\sample.wav" `
  -F "output_formats=json,srt,txt" `
  -F "source_type=audio"
```

可用参数：

- `file` 必填，本地上传文件
- `output_formats` 可选，默认 `json,srt,txt`
- `source_type` 可选，`audio | video | auto`
- `language` 可选，强制语言

### 2. Query Job

```powershell
curl.exe "http://127.0.0.1:8010/jobs/<job_id>"
```

### 3. Get Result JSON

```powershell
curl.exe "http://127.0.0.1:8010/jobs/<job_id>/result"
```

### 4. Download Artifacts

```powershell
curl.exe "http://127.0.0.1:8010/jobs/<job_id>/artifacts/srt"
curl.exe "http://127.0.0.1:8010/jobs/<job_id>/artifacts/txt"
curl.exe "http://127.0.0.1:8010/jobs/<job_id>/artifacts/json"
```

### 5. Health Check

```powershell
curl.exe "http://127.0.0.1:8010/health"
```

## CLI

提交文件：

```powershell
stt submit D:\path\file.wav --source-type audio
```

查看状态：

```powershell
stt status <job_id>
```

查看结果：

```powershell
stt result <job_id> --format json
stt result <job_id> --format srt
stt result <job_id> --format txt
```

健康检查：

```powershell
stt health
```

## Output Layout

每个任务都会在 `data/jobs/<job_id>/` 下生成自己的结果目录，例如：

```text
data/jobs/<job_id>/
  input.wav
  result.json
  result.srt
  result.txt
  chunks/           # 仅长音频切片时出现
```

`result.json` 中包含：

- 转写文本
- 语言
- 分段
- 文件路径
- 转写耗时指标 `metrics`

## Typical Workflow

推荐工作流：

1. 用 `yt-dlp` 或其他工具下载视频 / 音频
2. 把本地文件交给本项目转写
3. 查看 `result.txt / result.srt / result.json`
4. 再把转写结果交给其他分析层做摘要或详细报告

## Current Limitations

- 视频下载不在本项目内
- 项目只处理本地文件，不直接接收在线视频 URL
- 上游 Qwen3-ASR 的原始文本质量会影响最终字幕质量
- 当前做了基础清洗，但不是人工级字幕校对

## Testing

```powershell
pytest -q
```

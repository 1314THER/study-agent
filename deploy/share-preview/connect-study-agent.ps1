$ErrorActionPreference = 'Stop'
$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$keygen = Join-Path $env:WINDIR 'System32\OpenSSH\ssh-keygen.exe'
$key = Join-Path $HOME '.ssh\study-agent-viewer'
$pub = "$key.pub"
$url = 'http://127.0.0.1:18000/home.html'
$health = 'http://127.0.0.1:18000/openapi.json'

if (-not (Test-Path $ssh) -or -not (Test-Path $keygen)) {
    Write-Host '未找到 Windows OpenSSH 客户端，请先安装系统的 OpenSSH Client 可选功能。'
    exit 1
}

if (-not (Test-Path $key)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $key) | Out-Null
    Write-Host '首次使用：为这台 Windows 电脑创建专用 SSH 密钥。'
    Write-Host '可设置密钥口令；如果留空，以后双击即可直接连接。'
    & $keygen -t ed25519 -f $key -C study-agent-viewer
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Get-Content -Raw -Path $pub | Set-Clipboard
    Write-Host '公钥已复制到剪贴板，请发给主人授权。只发送公钥，不要发送私钥。'
    Write-Host '授权完成后再次双击 .cmd 文件。'
    Read-Host '按回车关闭窗口'
    exit 0
}

function Test-StudyAgent {
    try {
        $result = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2
        return ($result.StatusCode -eq 200 -and $result.Content.Contains('"/agent/context"'))
    } catch {
        return $false
    }
}

if (Test-StudyAgent) {
    Start-Process $url
    exit 0
}

Write-Host '首次连接时，请在弹出的 SSH 窗口核对服务器 ED25519 指纹：'
Write-Host 'SHA256:/jN3UQmpWPnPXFvFDTi2FVEQwZ/JrtRBDiB0IJliwi4'
Write-Host 'SSH 窗口需要保持打开，关闭它就会断开网页连接。'
$sshArgs = '-i "{0}" -o IdentitiesOnly=yes -o ExitOnForwardFailure=yes -N -L 127.0.0.1:18000:127.0.0.1:8000 studyviewer@47.117.107.156' -f $key
$process = Start-Process -FilePath $ssh -ArgumentList $sshArgs -PassThru

for ($i = 0; $i -lt 120; $i++) {
    if (Test-StudyAgent) {
        Start-Process $url
        exit 0
    }
    if ($process.HasExited) {
        Write-Host "SSH 已退出，代码 $($process.ExitCode)。请确认主人已经授权公钥。"
        exit 1
    }
    Start-Sleep -Seconds 1
}

Write-Host '等待连接超时。请查看 SSH 窗口中的提示。'
exit 1

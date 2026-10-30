# PowerShell: 新加坡 Windows 宝塔 443 SNI 分流配置助手
# 用法: 在 Singapore Windows PowerShell (管理员模式) 执行

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "🪟 Windows 宝塔 443 端口 SNI 预分流配置助手" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$NginxPaths = @(
    "C:\BtSoft\nginx\conf\nginx.conf",
    "C:\www\server\nginx\conf\nginx.conf",
    "D:\BtSoft\nginx\conf\nginx.conf"
)

$ConfPath = $null
foreach ($p in $NginxPaths) {
    if (Test-Path $p) {
        $ConfPath = $p
        break
    }
}

if (-not $ConfPath) {
    Write-Host "⚠️ 未在默认路径找到宝塔 Nginx 配置文件，请手动指定路径。" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ 找到 Nginx 配置文件: $ConfPath" -ForegroundColor Green

# 备份
$BakPath = "$ConfPath.bak-sni-$(Get-Date -Format 'yyyyMMddHHmmss')"
Copy-Item $ConfPath $BakPath
Write-Host "📦 已备份原配置至: $BakPath" -ForegroundColor Green

$StreamConf = @"

# >>> sing-box reality sni multiplexer >>>
stream {
    map `$ssl_preread_server_name `$backend_router {
        www.microsoft.com   127.0.0.1:8443;
        default             127.0.0.1:10443;
    }
    server {
        listen 443;
        proxy_pass `$backend_router;
        ssl_preread on;
    }
}
# <<< sing-box reality sni multiplexer <<<
"@

$Content = Get-Content $ConfPath -Raw
if ($Content -match "singbox_reality" -or $Content -match "backend_router") {
    Write-Host "ℹ️ 配置文件中已存在 Stream 分流规则，跳过追加。" -ForegroundColor Cyan
} else {
    Add-Content -Path $ConfPath -Value $StreamConf
    Write-Host "✅ 已追加 Stream 预分流规则至 Nginx 配置顶层。" -ForegroundColor Green
}

Write-Host "`n后续操作步骤：" -ForegroundColor Yellow
Write-Host "1. 在宝塔面板中，将现有 443 站点的监听端口修改为 10443"
Write-Host "2. 打开 CMD 运行: nginx -t 检查语法"
Write-Host "3. 运行: nginx -s reload 重载生效"
Write-Host "4. 此时外网连接 43.163.4.104:443 即可直通 Reality 节点！" -ForegroundColor Green

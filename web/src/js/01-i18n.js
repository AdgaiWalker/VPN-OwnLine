  var I18N = {
    en: {
      brand_sub: "OwnLine",
      status_checking: "Checking…",
      status_all_ok: "All Nodes Operational",
      status_n_bad: " Nodes Degraded",
      status_1_bad: "1 Node Degraded",
      status_no_nodes: "No Nodes Connected",
      topbar_settings: "Settings",
      main_title: "Connection Profiles",
      status_loaded: "Ready",
      btn_add_node: "+ Add Node",
      btn_back: "← Back",
      quota_hero_title: "Total Monthly Egress",
      quota_status_ok: "Normal",
      quota_rem_lbl: "Remaining: ",
      quota_safe_lbl: "All egress servers within quota limits",
      connecting_svc: "Connecting to service…",
      connect_device: "Connect This Device",
      copy_link: "Copy Link",
      scan_qr: "Scan QR",
      select_client: "Select Client",
      sr_badge: "Recommended for iOS",
      clash_badge: "Cross-platform",
      flclash_badge: "Cross-platform",
      btn_open: "Open",
      btn_download: "Download",
      launching_client: "Launching client…",
      not_installed: "Client not installed?",
      need_us_apple_id: "Need US Apple ID?",
      free_account_notice: "Free account: idapp.app (App Store only, never sign in to iCloud).",
      free_acc_prefix: "Free account: ",
      free_acc_suffix: " (App Store only, never sign in to iCloud).",
      clash_ios_help: "Clash: Please select the appropriate iOS download channel.",
      manual_copy_toggle: "Manual Link Copy & QR Code",
      sub_empty: "Subscription link unavailable",
      sub_copy_btn: "Copy Subscription Link",
      rotate_btn: "Revoke Old Subscription",
      scan_qr_title: "Scan QR to Import",
      scan_qr_desc: "Scan with system camera or Shadowrocket to import.",
      relay_dialog_title: "Configure as Low-Latency Relay",
      relay_dialog_desc: "Select the overseas egress landing node directly connected by this domestic server (prevents stutter & packet loss):",
      nodes_title: "Managed Nodes",
      nodes_loading: "Loading node list…",
      nodes_empty: "No nodes connected yet.",
      nodes_export_backup: "Backup Nodes",
      nodes_restore_backup: "Restore Config",
      backup_note_desc: "Restoring will only update node configurations.",
      btn_speedtest: "Speedtest",
      quota_section_title: "Quota & Circuit Breaker Settings",
      quota_heading: "Server Traffic",
      quota_loading: "Loading quota statistics…",
      quota_threshold_lbl: "Circuit breaker threshold (1–100%)",
      quota_threshold_desc: "When monthly traffic reaches this threshold, egress is automatically halted to prevent overages.",
      quota_save_btn: "Save",
      setup_title: "Add Server",
      tab_ssh: "Direct SSH",
      tab_tc: "Tencent Cloud API",
      tc_desc: "Automatically discover Lighthouse VPS via API keys.",
      tc_status_unconnected: "Backend discovery not configured. Please set up in Tencent Cloud Console.",
      tc_cred_title: "Tencent Cloud API Credentials",
      tc_cred_note: "Credentials are saved locally on this server only.",
      tc_need_assist: "Need setup assistance?",
      tc_copy_ai_prompt: "Copy AI Prompt",
      tc_btn_read: "List Instances",
      tc_guide_summary: "Purchasing & Environment Setup",
      tc_cloud_install: "Install via Cloud Terminal",
      tc_run_as_root: "Run as root on Ubuntu 22.04 or Debian 12:",
      btn_copy_install_cmd: "Copy Install Command",
      ssh_need_assist: "Need autonomous onboarding with local Agent?",
      ssh_copy_ai_prompt: "Copy Agent Task Brief",
      ssh_input_guide: "Enter two details, test the connection, then confirm installation.",
      lbl_pub_ip: "Public IP",
      lbl_root_pwd: "Server Password or SSH Private Key",
      ssh_defaults_note: "Defaults: root account, port 22. Open connection settings for another account or an encrypted key.",
      ssh_advanced_summary: "Connection Settings (Account, Port, Key Passphrase)",
      lbl_ssh_user: "Username",
      lbl_ssh_port: "SSH Port",
      lbl_ssh_passphrase: "Key Passphrase",
      btn_test_conn: "Test Connection",
      status_web_test_unavail: "Web check unavailable.",
      install_ready_title: "Ready to Install",
      install_defaults_note: "A name is filled in and the role defaults to automatic detection. Start installation or expand the options below to customize.",
      install_options_summary: "Customize Installation (Optional)",
      lbl_node_name: "Node Name",
      lbl_role: "Role",
      opt_role_auto: "Auto-detect (Recommended)",
      opt_role_exit: "Egress Landing Node",
      opt_role_relay: "Domestic Relay Node",
      btn_start_install: "Start Node Installation",
      terminal_install_summary: "Install via Terminal",
      logs_heading: "Runtime & Diagnostic Logs",
      logs_click_expand: "Click to expand",
      logs_subheading: "Recent system events and subscription logs",
      logs_health_btn: "Health Check",
      logs_copy_diag_btn: "Copy Diagnostics",
      btn_refresh_logs: "Refresh Logs",
      logs_view_all: "View All",
      log_tab_all: "All",
      log_tab_bad: "Errors",
      log_tab_sub: "Subscription",
      log_tab_probe: "Probes",
      logs_loading: "Loading logs…",
      logs_core_summary: "Core service logs: sing-box · Caddy · Admin",
      backup_dialog_title: "Backup Encryption Passphrase",
      backup_dialog_desc: "This passphrase is used strictly for in-browser encryption and decryption. If lost, it cannot be recovered.",
      backup_pwd_lbl: "Backup Passphrase",
      backup_confirm_lbl: "Confirm Passphrase",
      backup_cancel: "Cancel",
      backup_submit: "Continue",
      footer_settings: "Preferences",
      footer_account_security: "Account & Security",
      footer_change_pass: "Account & Security",
      settings_title: "Preferences",
      settings_lang_lbl: "Interface Language",
      settings_btn_done: "Done",
      account_dialog_title: "Account & Security",
      account_role_admin: "System Admin",
      account_auth_desc: "Protected by Basic Auth & Rate Limiting",
      account_curr_pass: "Current Password",
      account_hint_curr_pass: "(Identity Verification)",
      account_opt_user: "Change Login Username",
      account_hint_opt_user: "(leave empty to keep current)",
      account_new_user: "New Username",
      account_tip_username: "Supports 1-64 letters, numbers, _, ., or -",
      account_new_pass: "New Password",
      account_hint_new_pass: "(at least 12 characters)",
      account_confirm_pass: "Confirm New Password",
      account_btn_cancel: "Cancel",
      account_btn_save: "Save Changes",
      account_success_title: "Credentials Updated Successfully",
      account_success_subdesc: "New credentials saved. Please re-authenticate.",
      account_btn_relogin: "Log In With New Credentials",
      settings_cred_title: "Web Login Credentials",
      settings_cred_desc: "Change your administrator username and password for web portal access.",
      settings_curr_user: "Current Account",
      settings_curr_pass: "Current Password",
      settings_username: "New Username",
      settings_hint_username: "(leave empty to keep current)",
      settings_new_pass: "New Password",
      settings_hint_new_pass: "(at least 12 characters)",
      settings_confirm_pass: "Confirm New Password",
      settings_btn_cancel: "Cancel",
      settings_btn_save: "Save Changes",
      settings_version_lbl: "System Version",
      update_status_latest: "Up to Date",
      update_desc_latest: "Running the latest release",
      btn_check_update: "Check for Updates",
      btn_checking: "Checking…",
      update_found_title: "Update Available",
      update_found_desc: "New version is ready to install",
      btn_upgrade_now: "Upgrade Now",
      update_progress_title: "Upgrading System…",
      update_progress_desc: "Downloading core files & restarting service. All data preserved.",
      update_success_msg: "Successfully upgraded to latest version!",
      confirm_upgrade_title: "Confirm System Upgrade",
      confirm_upgrade_desc: "Upgrade to {version}? Service will reload smoothly with zero data loss."
    },
    zh: {
      brand_sub: "OwnLine",
      status_checking: "检测中...",
      status_all_ok: "运行正常",
      status_n_bad: " 个节点异常",
      status_1_bad: "1 个节点异常",
      status_no_nodes: "未连接节点",
      topbar_settings: "设置",
      main_title: "连接配置",
      status_loaded: "已加载",
      btn_add_node: "+ 添加节点",
      btn_back: "← 返回",
      quota_hero_title: "本月出海总流量",
      quota_status_ok: "充足",
      quota_rem_lbl: "剩余：",
      quota_safe_lbl: "所有出口服务器均在安全配额内 · 国内专线为防卡顿跳板",
      connecting_svc: "正在连接服务...",
      connect_device: "连接本机",
      copy_link: "复制链接",
      scan_qr: "扫码连接",
      select_client: "选择客户端",
      sr_badge: "iOS 推荐",
      clash_badge: "全平台通用",
      flclash_badge: "全平台通用",
      btn_open: "打开",
      btn_download: "前往下载",
      launching_client: "正在唤起客户端...",
      not_installed: "未安装客户端？",
      need_us_apple_id: "需要美区 Apple ID？",
      free_account_notice: "免费账号：idapp.app（仅在 App Store 登录，切勿登录 iCloud）。",
      free_acc_prefix: "免费账号：",
      free_acc_suffix: "（仅在 App Store 登录，切勿登录 iCloud）。",
      clash_ios_help: "Clash: 请选择适用的 iOS 下载渠道。",
      manual_copy_toggle: "手动复制链接与撤销",
      sub_empty: "订阅链接暂不可用",
      sub_copy_btn: "复制订阅链接",
      rotate_btn: "撤销旧订阅",
      scan_qr_title: "扫码导入订阅",
      scan_qr_desc: "请使用系统相机或小火箭扫描添加。",
      relay_dialog_title: "设为中转加速专线",
      relay_dialog_desc: "选择该国内服务器直达的海外出海落地节点（防卡顿与丢包）：",
      nodes_title: "节点列表",
      nodes_loading: "正在加载节点列表...",
      nodes_empty: "暂未连接任何节点。",
      nodes_export_backup: "备份节点",
      nodes_restore_backup: "恢复配置",
      backup_note_desc: "恢复操作只会替换节点配置。",
      btn_speedtest: "测速",
      quota_section_title: "流量熔断保护设置",
      quota_heading: "服务器流量",
      quota_loading: "正在加载流量统计...",
      quota_threshold_lbl: "超额熔断阈值 (1–100%)",
      quota_threshold_desc: "当月流量达到此阈值时，服务器自动暂停出口以防止超额扣费。",
      quota_save_btn: "保存",
      setup_title: "添加服务器",
      tab_ssh: "SSH 直连",
      tab_tc: "腾讯云 API",
      tc_desc: "通过 API 密钥自动发现轻量云主机。",
      tc_status_unconnected: "未连接授权后端。请在腾讯云控制台配置。",
      tc_cred_title: "腾讯云 API 凭据",
      tc_cred_note: "凭据仅保存在当前服务器本机。",
      tc_need_assist: "需要辅助创建？",
      tc_copy_ai_prompt: "复制 AI 提示词",
      tc_btn_read: "读取实例列表",
      tc_guide_summary: "选购与环境准备",
      tc_cloud_install: "通过云终端安装",
      tc_run_as_root: "以 root 权限在 Ubuntu 22.04 或 Debian 12 运行：",
      btn_copy_install_cmd: "复制安装命令",
      ssh_need_assist: "借助本地 Agent 全自动装配？",
      ssh_copy_ai_prompt: "复制 Agent 任务书",
      ssh_input_guide: "填写两项信息，先检测连接，再确认安装。",
      lbl_pub_ip: "公网 IP",
      lbl_root_pwd: "服务器密码或 SSH 私钥",
      ssh_defaults_note: "默认使用 root 账号、22 端口；其他账号或加密私钥请展开连接设置。",
      ssh_advanced_summary: "连接设置（账号、端口、私钥密码）",
      lbl_ssh_user: "用户名",
      lbl_ssh_port: "SSH 端口",
      lbl_ssh_passphrase: "私钥密码",
      btn_test_conn: "测试连接",
      status_web_test_unavail: "网页测试不可用。",
      install_ready_title: "就绪，可开始安装",
      install_defaults_note: "名称已自动填写，用途默认自动判定。可直接开始安装，或展开下方选项修改。",
      install_options_summary: "自定义安装（可选）",
      lbl_node_name: "节点名称",
      lbl_role: "角色",
      opt_role_auto: "自动判定（推荐）",
      opt_role_exit: "出口落地节点",
      opt_role_relay: "国内中继节点",
      btn_start_install: "开始安装节点",
      terminal_install_summary: "通过终端安装",
      logs_heading: "运行与诊断日志",
      logs_click_expand: "点击展开",
      logs_subheading: "近期系统运行事件与订阅日志",
      logs_health_btn: "健康检查",
      logs_copy_diag_btn: "复制诊断",
      btn_refresh_logs: "刷新日志",
      logs_view_all: "查看全部",
      log_tab_all: "全部",
      log_tab_bad: "仅错误",
      log_tab_sub: "订阅",
      log_tab_probe: "探活",
      logs_loading: "正在加载日志流...",
      logs_core_summary: "核心服务日志：sing-box · Caddy · 管理员",
      backup_dialog_title: "备份加密口令",
      backup_dialog_desc: "备份口令仅用于浏览器本地加密与解密，遗失后无法找回，请妥善保管。",
      backup_pwd_lbl: "备份口令",
      backup_confirm_lbl: "确认备份口令",
      backup_cancel: "取消",
      backup_submit: "继续",
      footer_settings: "偏好设置",
      footer_account_security: "账户与安全",
      footer_change_pass: "账户与安全",
      settings_title: "偏好设置",
      settings_lang_lbl: "界面语言",
      settings_btn_done: "完成",
      account_dialog_title: "账户与安全",
      account_role_admin: "系统管理员",
      account_auth_desc: "受 HTTP 基础凭据与防暴力破解策略保护",
      account_curr_pass: "当前密码",
      account_hint_curr_pass: "（验证身份）",
      account_opt_user: "修改登录用户名",
      account_hint_opt_user: "（如不修改请留空/保持当前）",
      account_new_user: "新用户名",
      account_tip_username: "支持 1-64 位英文字母、数字、下划线、点或横线",
      account_new_pass: "新密码",
      account_hint_new_pass: "（至少 12 个字符）",
      account_confirm_pass: "确认新密码",
      account_btn_cancel: "取消",
      account_btn_save: "保存更改",
      account_success_title: "管理凭据修改成功",
      account_success_subdesc: "新凭据已安全生效，请使用新凭据重新登录。",
      account_btn_relogin: "立即使用新凭据登录",
      settings_cred_title: "Web 管理登录凭据",
      settings_cred_desc: "修改访问当前管理面板的用户名与登录密码。",
      settings_curr_user: "当前账号",
      settings_curr_pass: "当前密码",
      settings_username: "新用户名",
      settings_hint_username: "（如不修改请留空）",
      settings_new_pass: "新密码",
      settings_hint_new_pass: "（至少 12 个字符）",
      settings_confirm_pass: "确认新密码",
      settings_btn_cancel: "取消",
      settings_btn_save: "保存更改",
      settings_version_lbl: "系统版本",
      update_status_latest: "已是最新版本",
      update_desc_latest: "当前正在运行最新稳定版本",
      btn_check_update: "检查更新",
      btn_checking: "正在检查...",
      update_found_title: "发现新版本",
      update_found_desc: "有可用的系统更新",
      btn_upgrade_now: "立即更新",
      update_progress_title: "正在平滑更新...",
      update_progress_desc: "正在下载核心代码并热重启服务，数据完全保留，请稍候...",
      update_success_msg: "系统已成功升级至最新版本！",
      confirm_upgrade_title: "确认系统升级",
      confirm_upgrade_desc: "确认平滑升级至 {version} 吗？服务将自动热重启，已有配置与节点数据 100% 保留。"
    }
  };

  function getLanguage() {
    if (typeof window === 'undefined' || !window.localStorage) {
      return 'zh';
    }
    return window.localStorage.getItem('ownline_lang') || 'en';
  }

  function isZh() {
    return getLanguage() === 'zh';
  }

  function t(key) {
    var lang = getLanguage();
    var dict = I18N[lang] || I18N.en;
    if (dict && dict[key] != null) return dict[key];
    if (I18N.en && I18N.en[key] != null) return I18N.en[key];
    return key;
  }

  function applyLanguage() {
    var zh = isZh();
    if (typeof document === 'undefined') return;
    if (document.documentElement) {
      document.documentElement.lang = zh ? 'zh-CN' : 'en';
    }
    var i18nElements = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < i18nElements.length; i++) {
      var el = i18nElements[i];
      var key = el.getAttribute('data-i18n');
      var val = t(key);
      if (val) el.textContent = val;
    }
    var optEn = document.getElementById('opt-lang-en');
    var optZh = document.getElementById('opt-lang-zh');
    if (optEn) optEn.checked = !zh;
    if (optZh) optZh.checked = zh;

    var btnAccount = document.getElementById('btn-open-account');
    if (btnAccount) {
      var accText = zh ? '账户与安全' : 'Account & Security';
      btnAccount.title = accText;
      btnAccount.setAttribute('aria-label', accText);
    }
    var btnSettings = document.getElementById('btn-open-settings');
    if (btnSettings) {
      var sText = zh ? '偏好设置' : 'Preferences';
      btnSettings.title = sText;
      btnSettings.setAttribute('aria-label', sText);
    }
    var btnAddNode = document.getElementById('btn-enter-setup');
    if (btnAddNode) {
      var aText = zh ? '添加节点' : 'Add Node';
      btnAddNode.title = aText;
      btnAddNode.setAttribute('aria-label', aText);
    }
    var btnCopySub = document.getElementById('btn-copy-sub');
    if (btnCopySub) {
      var cText = zh ? '复制链接' : 'Copy Link';
      btnCopySub.title = cText;
      btnCopySub.setAttribute('aria-label', cText);
    }
    var btnHeroQr = document.getElementById('btn-hero-qr');
    if (btnHeroQr) {
      var qText = zh ? '扫码连接' : 'Scan QR';
      btnHeroQr.title = qText;
      btnHeroQr.setAttribute('aria-label', qText);
    }
    var btnPing = document.getElementById('btn-ping-action');
    if (btnPing) {
      var pText = zh ? '测速' : 'Speedtest';
      btnPing.title = pText;
      btnPing.setAttribute('aria-label', pText);
    }
    var btnCancelSetup = document.getElementById('btn-cancel-setup');
    if (btnCancelSetup) {
      var bText = zh ? '返回' : 'Back';
      btnCancelSetup.title = bText;
      btnCancelSetup.setAttribute('aria-label', bText);
    }
    var inputUser = document.getElementById('settings-username');
    if (inputUser) {
      var curr = STATE.currentUsername || '';
      inputUser.placeholder = zh ? (curr ? ('保持当前用户名 (' + curr + ')') : '如不修改请留空') : (curr ? ('Keep current (' + curr + ')') : 'Leave empty to keep current');
    }

    if (typeof detectClient === 'function') detectClient();
    if (typeof paintStatus === 'function') paintStatus();
    if (typeof renderNodes === 'function' && Array.isArray(NODES)) renderNodes(NODES, STATUS, STATE.quota);
    if (typeof renderQuota === 'function' && STATE.quota) renderQuota(STATE.quota);
  }

  function setLanguage(lang) {
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.setItem('ownline_lang', lang);
    }
    applyLanguage();
  }
  window.setLanguage = setLanguage;


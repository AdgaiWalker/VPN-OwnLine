import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  CheckCircle,
  Circle,
  Eye,
  EyeSlash,
  X,
  CaretLeft,
  CaretRight,
  ArrowUpRight,
  WarningCircle,
  SpinnerGap,
  Copy,
  TerminalWindow,
} from "@phosphor-icons/react";
import { WebDialog } from "./WebDialog";
import {
  STORE_KEY as STORE,
  INITIAL_SNAPSHOT as initial,
  STEP_TITLES as titles,
  INSTALL_PHASES as phases,
  PROVIDERS_CATALOG as providers,
  BOOTSTRAP_COMMAND as command,
  DEMO_SUBSCRIPTION_URL as subscription,
} from "./constants/providers.ts";
import type { Step, Panel, Snapshot, ProviderItem } from "./types/prototype.ts";
import { browserPlatform, validHost, demoPassword } from "./utils/platform.ts";
import { getClientApps } from "./utils/clientMatrix.ts";

function load(): Snapshot {
  try {
    const s = JSON.parse(localStorage.getItem(STORE) || "null");
    if (
      s &&
      typeof s.purchased === "boolean" &&
      [0, 1, 2, 3].includes(s.active)
    )
      return { ...initial, ...s };
  } catch {
    /* A private-browser session still works in memory. */
  }
  return initial;
}

export default function Prototype() {
  const [state, setState] = useState<Snapshot>(load);
  const [password, setPassword] = useState("demo-password");
  const [privateKey, setPrivateKey] = useState("");
  const [keyMode, setKeyMode] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [dashboardRevealed, setDashboardRevealed] = useState(false);
  const [panel, setPanel] = useState<Panel>(null);
  const [provider, setProvider] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [phase, setPhase] = useState(0);
  const [copyState, setCopyState] = useState("");
  const [manualCopy, setManualCopy] = useState("");
  const [importApp, setImportApp] = useState("");
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [samplePassword, setSamplePassword] = useState(demoPassword);
  const failNext = useRef(false);
  const checkTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const [deviceId] = useState(browserPlatform);
  const clientDone = !!confirmed[deviceId];
  const done = [state.purchased, state.connected, state.installed, clientDone];
  const running = state.started !== null;
  const apps = getClientApps(deviceId);

  useEffect(() => {
    try {
      localStorage.setItem(STORE, JSON.stringify(state));
    } catch {
      /* Persistence is optional for this demo. */
    }
  }, [state]);
  useEffect(() => {
    if (state.started === null) return;
    const update = () => {
      const next = Math.floor((Date.now() - state.started!) / 1000);
      setPhase(Math.min(4, next));
      if (next >= 5) {
        setState((s) => ({ ...s, installed: true, started: null, active: 2 }));
        setSamplePassword(demoPassword());
      }
    };
    update();
    const timer = setInterval(update, 200);
    return () => clearInterval(timer);
  }, [state.started]);
  useEffect(
    () => () => {
      if (checkTimer.current) clearTimeout(checkTimer.current);
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  function open(next: Panel, which: number | null = null) {
    setProvider(which);
    setCopyState("");
    setManualCopy("");
    setPanel(next);
  }
  function change(key: "host" | "user" | "port", value: string) {
    setError("");
    setState((s) => ({ ...s, [key]: value }));
  }
  function chooseStep(step: Step) {
    if ((step > 1 && !state.connected) || (step === 3 && !state.installed))
      return;
    setState((s) => ({ ...s, active: step, hidden: false }));
  }
  function reset(fresh = false, failure = false) {
    if (checkTimer.current) clearTimeout(checkTimer.current);
    setChecking(false);
    setState({ ...initial, purchased: !fresh, active: fresh ? 0 : 1 });
    setPassword("demo-password");
    setPrivateKey("");
    setKeyMode(false);
    setError("");
    setPhase(0);
    setConfirmed({});
    setDashboardRevealed(false);
    setPanel(null);
    failNext.current = failure;
  }
  function connect(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    if (!validHost(state.host.trim())) {
      setError("请输入公网 IP 或服务器域名。");
      return;
    }
    if (!state.user.trim()) {
      setError("请输入服务器的 SSH 用户名。");
      return;
    }
    if (!(Number(state.port) >= 1 && Number(state.port) <= 65535)) {
      setError("SSH 端口范围为 1–65535。");
      return;
    }
    if (keyMode ? !privateKey.includes("PRIVATE KEY") : !password) {
      setError(
        keyMode ? "请选择或粘贴完整私钥。" : "请输入服务器密码，或改用私钥。",
      );
      return;
    }
    setChecking(true);
    checkTimer.current = setTimeout(() => {
      setChecking(false);
      if (failNext.current) {
        failNext.current = false;
        setError(
          `模拟连接失败（端口 ${state.port}）。请检查 SSH 地址和登录信息后重试。`,
        );
        return;
      }
      setPassword("");
      setPrivateKey("");
      setState((s) => ({ ...s, purchased: true, connected: true, active: 2 }));
    }, 1100);
  }
  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopyState(label);
      setManualCopy("");
      if (copyTimer.current) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopyState(""), 2200);
    } catch {
      setManualCopy(text);
      setCopyState("");
    }
  }
  function startInstall() {
    setError("");
    setDashboardRevealed(false);
    setPhase(0);
    setState((s) => ({ ...s, started: Date.now(), active: 2 }));
  }
  const ext = (url: string, label: ReactNode, className = "external-link") => (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className={className}
    >
      {label}
      <ArrowUpRight size={15} aria-hidden="true" />
    </a>
  );
  const alert = error ? (
    <div className="inline-error" role="alert">
      <WarningCircle size={19} aria-hidden="true" />
      <span>{error}</span>
    </div>
  ) : null;
  const groupedInput = (
    label: string,
    id: string,
    value: string,
    onChange: (value: string) => void,
    type = "text",
  ) => (
    <label className="login-row" htmlFor={id}>
      <span>{label}</span>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={type}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}

        disabled={checking}
      />
    </label>
  );

  function importControls() {
    return (
      <div className="import-controls">
        <p className="micro-label">导入客户端</p>
        <div className="app-buttons">
          {apps.map((app) => (
            <button
              className="primary app-button"
              type="button"
              key={app}
              onClick={() => {
                setImportApp(app);
                open("import");
              }}
            >
              {app}
            </button>
          ))}
        </div>
        <button
          className="text-button copy-link"
          onClick={() => copy(subscription, "link")}
        >
          {copyState === "link" ? "已复制" : "复制链接"}
        </button>
        {manualCopy && (
          <div className="manual-copy">
            <p>请选择并复制链接。</p>
            <input aria-label="订阅链接" readOnly value={manualCopy} />
          </div>
        )}
        {(deviceId === "ios" || deviceId === "mac") && (
          <p className="muted app-note">
            下载 Shadowrocket 需要中国大陆以外地区的 App Store 账号。
          </p>
        )}
      </div>
    );
  }
  function taskBody(step: number) {
    if (step === 0)
      return (
        <div className="task-content purchase-content">
          <p>
            选择中国大陆以外地区的 Linux 服务器，同时核对续费、公网 IP
            和流量费用。
          </p>
          <button className="primary" onClick={() => open("providers")}>
            了解服务器
          </button>
          <button
            className="text-button"
            onClick={() =>
              setState((s) => ({ ...s, purchased: true, active: 1 }))
            }
          >
            我已有服务器
          </button>
        </div>
      );
    if (step === 1 && state.connected)
      return (
        <div className="task-content">
          <div className="status-line">
            <CheckCircle weight="fill" size={20} />
            <span>服务器连接成功 · 模拟</span>
          </div>
          <dl className="facts">
            <div>
              <dt>服务器</dt>
              <dd>{state.host}</dd>
            </div>
            <div>
              <dt>系统</dt>
              <dd>Ubuntu 22.04 · amd64</dd>
            </div>
            <div>
              <dt>SSH</dt>
              <dd>
                {state.user} · 端口 {state.port}
              </dd>
            </div>
          </dl>
          <button
            className="primary"
            onClick={() => chooseStep(state.installed ? 3 : 2)}
          >
            {state.installed ? "继续导入客户端" : "继续安装"}
          </button>
        </div>
      );
    if (step === 1)
      return (
        <form
          className="task-content access-content"
          onSubmit={connect}
          noValidate
        >
          <button
            type="button"
            className="text-button details-link"
            onClick={() => open("details")}
          >
            查找服务器信息
          </button>
          <div className="login-group">
            {groupedInput("公网 IP", "public-ip", state.host, (v) =>
              change("host", v),
            )}
            {groupedInput("用户名", "ssh-user", state.user, (v) =>
              change("user", v),
            )}
            {!keyMode && (
              <div className="login-row password-row">
                <label htmlFor="ssh-password">密码</label>
                <input
                  id="ssh-password"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError("");
                  }}
                  type={revealed ? "text" : "password"}
                  autoComplete="off"

                  disabled={checking}
                />
                <button
                  type="button"
                  className="eye-button"
                  aria-label={revealed ? "隐藏密码" : "显示密码"}
                  aria-pressed={revealed}
                  onClick={() => {
                    setRevealed((v) => !v);
                  }}
                >
                  {revealed ? <EyeSlash size={20} /> : <Eye size={20} />}
                </button>
              </div>
            )}
          </div>
          {keyMode && (
            <div className="private-key">
              <label htmlFor="private-key">SSH 私钥</label>
              <textarea
                id="private-key"
                value={privateKey}
                onChange={(e) => {
                  setPrivateKey(e.target.value);
                  setError("");
                }}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                rows={3}
              />
              <input
                className="file-input"
                ref={file}
                type="file"
                accept=".pem,.key,.txt,*/*"
                aria-label="选择私钥文件"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    if (f.size > 65536) {
                      setError("请选择小于 64 KB 的私钥文件。");
                      return;
                    }
                    setPrivateKey(await f.text());
                    setError("");
                  }
                }}
              />
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  file.current?.click();
                }}
              >
                选择私钥文件
              </button>
            </div>
          )}
          <div className="form-options">
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setKeyMode((v) => !v);
                setError("");
              }}
            >
              {keyMode ? "使用密码" : "使用私钥"}
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() => open("advanced")}
            >
              高级选项
            </button>
          </div>
          {alert}
          <button className="primary" type="submit" disabled={checking}>
            {checking && <SpinnerGap className="spin" size={18} />}
            {checking ? "正在检查…" : error ? "重试连接" : "连接"}
          </button>
          <p className="reassurance" role="status">
            {checking
              ? "正在模拟检查，不会连接真实服务器。"
              : "仅检查连接，暂不安装。"}
          </p>
          <a
            className="text-button cloud-link"
            href="https://console.cloud.tencent.com/lighthouse/"
            target="_blank"
            rel="noopener noreferrer"
          >
            腾讯云<span> · 查看服务器</span>
          </a>
          <p className="muted small">在腾讯云登录后查看公网 IP；打开控制台不等于授权账号。</p>
        </form>
      );
    if (step === 2 && running)
      return (
        <div className="task-content install-content" aria-live="polite">
          <div className="install-status">
            <SpinnerGap size={22} className="spin" />
            <strong>正在安装…</strong>
          </div>
          <p>{phases[phase]}</p>
          <div className="phase-list">
            {phases.map((name, i) => (
              <div
                key={name}
                className={i === phase ? "phase current-phase" : "phase"}
              >
                {i < phase ? (
                  <CheckCircle size={16} weight="fill" />
                ) : (
                  <Circle size={16} />
                )}
                <span>{name}</span>
              </div>
            ))}
          </div>
          <p className="muted small">模拟安装进度，可离开页面后继续查看。</p>
        </div>
      );
    if (step === 2 && state.installed)
      return (
        <div className="task-content delivery-content">
          <div className="status-line">
            <CheckCircle size={20} weight="fill" />
            <span>安装演示完成</span>
          </div>
          <p>管理网页账号与服务器登录账号相互独立。</p>
          <dl className="facts delivery-facts">
            <div>
              <dt>示例地址</dt>
              <dd>dashboard.evergreen.example</dd>
            </div>
            <div>
              <dt>管理账号</dt>
              <dd>admin</dd>
            </div>
            <div>
              <dt>示例密码</dt>
              <dd className="secret-result">
                {dashboardRevealed ? samplePassword : "••••••••••••"}
                <button
                  className="eye-button"
                  aria-label={
                    dashboardRevealed ? "隐藏示例管理密码" : "显示示例管理密码"
                  }
                  onClick={() => setDashboardRevealed((v) => !v)}
                >
                  {dashboardRevealed ? (
                    <EyeSlash size={19} />
                  ) : (
                    <Eye size={19} />
                  )}
                </button>
              </dd>
            </div>
          </dl>
          <button className="primary" onClick={() => chooseStep(3)}>
            进入管理页
          </button>
          <button
            className="text-button"
            onClick={() =>
              copy(
                `示例管理页：https://dashboard.evergreen.example\n账号：admin\n示例密码：${samplePassword}`,
                "details",
              )
            }
          >
            {copyState === "details" ? "已复制" : "复制访问信息"}
          </button>
          <p className="muted small">以上为示例访问信息，未实际安装服务器。</p>
        </div>
      );
    if (step === 2)
      return (
        <div className="task-content install-content">
          <div className="status-line">
            <CheckCircle size={20} weight="fill" />
            <span>服务器连接成功 · 模拟</span>
          </div>
          <dl className="facts">
            <div>
              <dt>服务器</dt>
              <dd>{state.host}</dd>
            </div>
            <div>
              <dt>系统</dt>
              <dd>Ubuntu 22.04 · amd64</dd>
            </div>
          </dl>
          <p>将在此服务器上安装长青管理网页与 sing-box。</p>
          <button className="primary" onClick={startInstall}>
            开始安装
          </button>
          <p className="muted small">交互演示，不会修改真实服务器。</p>
        </div>
      );
    return (
      <div className="task-content client-content">
        {importControls()}
        <p className="muted small">
          请在客户端内确认导入并连接。本原型不会打开本机应用。
        </p>
        <button
          className="text-button done-button"
          onClick={() => {
            setConfirmed((s) => ({ ...s, [deviceId]: true }));
            setState((s) => ({ ...s, hidden: true }));
          }}
        >
          完成
        </button>
      </div>
    );
  }
  const panelTitles: Record<Exclude<Panel, null>, string> = {
    help: "帮助",
    providers: "选择服务器",
    details: "查找服务器信息",
    advanced: "高级选项",
    command: "命令行",
    import: "导入演示",
    delivery: "管理页访问信息",
    scenarios: "体验原型",
  };
  const providerList = (buying: boolean) => (
    <div className="providers-list">
      {providers.map((p, i) => (
        <button
          className="provider-row"
          key={p.name}
          onClick={() => setProvider(i)}
        >
          <span>
            <strong>{p.name}</strong>
            <small>{buying ? p.kind : p.product}</small>
          </span>
          <CaretRight size={17} />
        </button>
      ))}
    </div>
  );

  return (
    <>
      <div className="app-screen evergreen-screen">
        <main className="evergreen-content" data-testid="evergreen-app">
          <header className="brand-header">
            <span className="wordmark">长青</span>
            <button
              className="text-button help-button"
              onClick={() => open("help")}
            >
              帮助
            </button>
          </header>
          {state.hidden ? (
            <section className="daily-view">
              <div className="section-heading">
                <h1>{state.installed ? "专线已就绪" : "完成设置"}</h1>
              </div>
              {state.installed ? (
                <>
                  <div className="status-line">
                    <CheckCircle weight="fill" size={19} />
                    <span>服务可用 · 模拟</span>
                  </div>
                  {importControls()}
                  <button
                    className="text-button"
                    onClick={() => open("delivery")}
                  >
                    管理页访问信息
                  </button>
                  <button
                    className="text-button"
                    onClick={() =>
                      setState((s) => ({ ...s, active: 3, hidden: false }))
                    }
                  >
                    设置清单
                  </button>
                </>
              ) : (
                <>
                  <p className="muted">进度已保存，可以接着完成设置。</p>
                  <button
                    className="primary"
                    onClick={() => setState((s) => ({ ...s, hidden: false }))}
                  >
                    继续设置
                  </button>
                </>
              )}
            </section>
          ) : (
            <section aria-label="设置清单">
              <div className="section-heading">
                <h1>完成设置</h1>
                <button
                  className="text-button hide-button"
                  onClick={() => {
                    setState((s) => ({ ...s, hidden: true }));
                  }}
                >
                  收起
                </button>
              </div>
              <ol className="task-list">
                {titles.map((title, i) => {
                  const active = state.active === i;
                  const locked =
                    (i > 1 && !state.connected) ||
                    (i === 3 && !state.installed);
                  return (
                    <li
                      className={`task${active ? " expanded" : ""}${done[i] ? " completed" : ""}`}
                      key={title}
                      data-task={i + 1}
                    >
                      <button
                        type="button"
                        className="task-heading"
                        onClick={() => chooseStep(i as Step)}
                        aria-expanded={active}
                        aria-controls={`task-body-${i}`}
                        aria-disabled={locked}
                        disabled={locked}
                        data-testid={`task-${i + 1}`}
                      >
                        <span
                          className={`task-marker${done[i] ? " checked" : active ? " active-marker" : ""}`}
                          aria-hidden="true"
                        >
                          {done[i] ? (
                            <CheckCircle weight="fill" size={26} />
                          ) : (
                            <>
                              <Circle weight="fill" size={26} />
                              <span>{i + 1}</span>
                            </>
                          )}
                        </span>
                        <span className="task-name">{title}</span>
                        <span className="sr-only">
                          {done[i] ? "已完成" : active ? "当前任务" : "未开始"}
                        </span>
                      </button>
                      {active && (
                        <div
                          id={`task-body-${i}`}
                          className="task-body"
                          data-testid="expanded-task"
                        >
                          {taskBody(i)}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            </section>
          )}
          <footer className="page-footer">
            <button className="text-button" onClick={() => open("command")}>
              命令行
            </button>
            <button
              className="prototype-button"
              onClick={() => open("scenarios")}
            >
              原型演示
            </button>
          </footer>
        </main>
      </div>
      <WebDialog
        open={panel !== null}
        onOpenChange={(next) => {
          if (!next) {
            setPanel(null);
          }
        }}
        title={panel ? panelTitles[panel] : ""}
      >
        <div className="evergreen-sheet">
          <button
            className="sheet-close"
            aria-label="关闭帮助面板"
            onClick={() => {
              setPanel(null);
            }}
          >
            <X size={21} />
          </button>
          {(panel === "providers" || panel === "details") &&
            (provider === null ? (
              <>
                <p className="sheet-intro">
                  {panel === "providers"
                    ? "请比较长期总费用，免费试用与免费额度的限制有所不同。"
                    : "选择云厂商，查找服务器、公网 IP 和 SSH 登录信息。登录将在厂商官网完成。"}
                </p>
                {providerList(panel === "providers")}
                {panel === "providers" && (
                  <p className="muted small">
                    选择中国大陆以外地区、Linux 系统和可访问的公网
                    IPv4，并核对续费、磁盘与流量费用。
                  </p>
                )}
              </>
            ) : (
              <>
                <button
                  className="text-button back-link"
                  onClick={() => setProvider(null)}
                >
                  <CaretLeft size={15} />
                  全部厂商
                </button>
                <h3>{providers[provider].name}</h3>
                <p className="muted">{providers[provider].product}</p>
                {panel === "details" ? (
                  <>
                    <ol className="help-steps">
                      <li>打开控制台，找到已购买的服务器，核对地区和名称。</li>
                      <li>复制公网 IPv4 地址，请勿填写内网地址。</li>
                      <li>
                        确认系统对应的 SSH
                        用户名，使用已保存的密码或私钥。忘记密码时可在控制台重置。
                      </li>
                    </ol>
                    {ext(providers[provider].console, "云控制台")}
                    {ext(providers[provider].guide, "官方登录指南")}
                    <p className="muted small">
                      打开云控制台不会授权长青访问账号，请勿在聊天中发送密码或私钥。
                    </p>
                    <button className="primary" onClick={() => setPanel(null)}>
                      返回连接服务器
                    </button>
                  </>
                ) : (
                  <>
                    <p>
                      购买前请核对地区、操作系统、流量额度、公网 IP 和续费价格。
                    </p>
                    {ext(providers[provider].buy, "官方产品页")}
                    <p className="muted small">
                      请自行购买或开通资源，本原型不会购买或创建服务器。
                    </p>
                    <button
                      className="primary"
                      onClick={() => {
                        setState((s) => ({ ...s, purchased: true, active: 1 }));
                        setPanel(null);
                      }}
                    >
                      我已有服务器
                    </button>
                  </>
                )}
              </>
            ))}
          {panel === "advanced" && (
            <>
              <p className="sheet-intro">
                SSH 用于连接 Linux 服务器，其端口与代理服务端口不同。
              </p>
              <div className="login-group">
                {groupedInput(
                  "SSH 端口",
                  "ssh-port",
                  state.port,
                  (v) => change("port", v),
                  "number",
                )}
              </div>
              <button
                className="primary"
                onClick={() => {
                  setPanel(null);
                }}
              >
                保存
              </button>
            </>
          )}
          {panel === "command" && (
            <>
              <p className="sheet-intro">
                熟悉服务器终端？可在自己的 Linux 服务器上运行以下命令。
              </p>
              <pre className="command-code">{command}</pre>
              <button
                className="primary"
                onClick={() => copy(command, "command")}
              >
                <Copy size={18} />
                {copyState === "command" ? "已复制" : "复制命令"}
              </button>
              <p className="muted small">
                复制不会执行命令。实际运行会修改目标服务器，本原型不会执行。
              </p>
            </>
          )}
          {panel === "import" && (
            <>
              <h3>{importApp}</h3>
              <p>
                实际使用时，会打开 {importApp}{" "}
                并传入订阅。请在客户端内确认导入后连接。
              </p>
              <p className="demo-notice">
                仅为演示，未打开本机应用，也未导入订阅。
              </p>
              {(deviceId === "ios" || deviceId === "mac") && (
                <>
                  <p className="small muted">
                    下载 Shadowrocket 需要中国大陆以外地区的 App Store 账号。
                  </p>
                  {ext(
                    "https://apps.apple.com/hk/app/shadowrocket/id932747118",
                    "App Store",
                  )}
                </>
              )}
              <button className="primary" onClick={() => setPanel(null)}>
                返回设置
              </button>
              <button
                className="text-button"
                onClick={() => copy(subscription, "link")}
              >
                {copyState === "link" ? "已复制" : "复制链接"}
              </button>
            </>
          )}
          {panel === "delivery" && (
            <>
              <p className="sheet-intro">
                以下为示例管理页信息，与 SSH 登录信息相互独立。
              </p>
              <dl className="facts">
                <div>
                  <dt>示例地址</dt>
                  <dd>dashboard.evergreen.example</dd>
                </div>
                <div>
                  <dt>账号</dt>
                  <dd>admin</dd>
                </div>
              </dl>
              <button
                className="primary"
                onClick={() =>
                  copy(
                    `示例地址：https://dashboard.evergreen.example\n账号：admin\n示例密码：${samplePassword}`,
                    "details",
                  )
                }
              >
                {copyState === "details" ? "已复制" : "复制访问信息"}
              </button>
            </>
          )}
          {panel === "help" && (
            <>
              <p className="sheet-intro">
                每次完成一项任务。服务器设置通用，客户端设置仅针对当前设备。
              </p>
              <div className="help-menu">
                <button
                  onClick={() => {
                    setState((s) => ({ ...s, hidden: false }));
                    setPanel(null);
                  }}
                >
                  设置清单
                  <CaretRight size={16} />
                </button>
                <button
                  onClick={() => {
                    setProvider(null);
                    setPanel("details");
                  }}
                >
                  查找服务器信息
                  <CaretRight size={16} />
                </button>
                <button onClick={() => setPanel("command")}>
                  命令行
                  <TerminalWindow size={17} />
                </button>
                <button onClick={() => setPanel("scenarios")}>
                  体验原型
                  <CaretRight size={16} />
                </button>
              </div>
            </>
          )}
          {panel === "scenarios" && (
            <>
              <p className="sheet-intro">
                交互原型：连接、安装和访问信息均为模拟，请仅使用示例信息。
              </p>
              <div className="help-menu">
                <button onClick={() => reset(true)}>
                  还没有服务器
                  <CaretRight size={16} />
                </button>
                <button onClick={() => reset()}>
                  已有服务器
                  <CaretRight size={16} />
                </button>
                <button onClick={() => reset(false, true)}>
                  体验连接失败
                  <CaretRight size={16} />
                </button>
                <button
                  onClick={() => {
                    reset();
                    setState((s) => ({
                      ...s,
                      connected: true,
                      installed: true,
                      active: 3,
                    }));
                  }}
                >
                  体验客户端导入
                  <CaretRight size={16} />
                </button>
              </div>
              <p className="muted small">
                浏览器仅保存不含敏感信息的演示进度，不保存密码、私钥或管理页密码。
              </p>
            </>
          )}
          {manualCopy && panel !== "help" && (
            <div className="manual-copy">
              <p>请选择并复制。</p>
              <textarea
                readOnly
                value={manualCopy}

                rows={3}
                aria-label="待复制文本"
              />
            </div>
          )}
        </div>
      </WebDialog>
    </>
  );
}

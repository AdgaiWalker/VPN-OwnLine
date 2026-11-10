import type { ProviderItem, Snapshot } from "../types/prototype.ts";

export const STORE_KEY = "evergreen-interaction-demo-v1";

export const INITIAL_SNAPSHOT: Snapshot = {
  purchased: true,
  connected: false,
  installed: false,
  active: 1,
  hidden: false,
  host: "203.0.113.10",
  user: "root",
  port: "22",
  started: null,
};

export const STEP_TITLES = ["购买服务器", "连接服务器", "安装与配置", "导入客户端"];

export const INSTALL_PHASES = [
  "准备服务器",
  "下载应用",
  "配置服务",
  "验证公网地址",
  "生成访问信息",
];

export const BOOTSTRAP_COMMAND =
  "curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash";

export const DEMO_SUBSCRIPTION_URL = "https://subscription.evergreen.example/s/demo";

export const PROVIDERS_CATALOG: ProviderItem[] = [
  {
    name: "腾讯云",
    product: "轻量应用服务器",
    kind: "付费套餐",
    buy: "https://www.tencentcloud.com/products/lighthouse",
    console: "https://console.cloud.tencent.com/lighthouse/",
    guide: "https://cloud.tencent.com/document/product/1207/44575",
  },
  {
    name: "阿里云",
    product: "轻量应用服务器",
    kind: "付费套餐",
    buy: "https://www.aliyun.com/product/swas",
    console: "https://swasnext.console.aliyun.com/",
    guide: "https://help.aliyun.com/en/simple-application-server/",
  },
  {
    name: "火山引擎",
    product: "云服务器",
    kind: "付费套餐",
    buy: "https://www.volcengine.com/product/ecs",
    console: "https://console.volcengine.com/ecs/",
    guide: "https://docs.volcengine.com/docs/ecs/",
  },
  {
    name: "华为云",
    product: "Flexus 应用服务器 L 实例",
    kind: "付费套餐",
    buy: "https://www.huaweicloud.com/intl/en-us/product/flexus-l.html",
    console: "https://console.huaweicloud.com/",
    guide: "https://support.huaweicloud.com/intl/en-us/productdesc-flexusl/",
  },
  {
    name: "雨云",
    product: "云服务器 · RCS",
    kind: "付费套餐",
    buy: "https://www.rainyun.com/rcs",
    console: "https://app.rainyun.com/",
    guide: "https://www.rainyun.com/rcs",
  },
  {
    name: "谷歌云",
    product: "Compute Engine",
    kind: "免费额度与试用",
    buy: "https://cloud.google.com/free",
    console: "https://console.cloud.google.com/compute/instances",
    guide: "https://docs.cloud.google.com/compute/docs/connect/standard-ssh",
  },
  {
    name: "甲骨文云",
    product: "OCI Compute",
    kind: "免费额度与试用",
    buy: "https://www.oracle.com/cloud/free/",
    console: "https://cloud.oracle.com/compute/instances",
    guide:
      "https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/accessinginstance.htm",
  },
  {
    name: "AWS",
    product: "Amazon EC2",
    kind: "免费额度与试用",
    buy: "https://aws.amazon.com/free/",
    console: "https://console.aws.amazon.com/ec2/home#Instances:",
    guide:
      "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-to-linux-instance.html",
  },
  {
    name: "微软 Azure",
    product: "Linux 虚拟机",
    kind: "免费额度与试用",
    buy: "https://azure.microsoft.com/en-us/free/",
    console:
      "https://portal.azure.com/#browse/Microsoft.Compute%2FVirtualMachines",
    guide:
      "https://learn.microsoft.com/en-us/azure/virtual-machines/linux-vm-connect",
  },
];

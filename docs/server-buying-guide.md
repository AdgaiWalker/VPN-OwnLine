# Server buying and preparation guide

Start here if you do not own a server yet. Compare the total ongoing cost of a suitable server, then return to [AI-assisted setup](../README.md#ai-assisted-setup). Already have one? Skip shopping and prepare its [SSH access](#prepare-your-server).

Official information checked on **2026-10-31**. Availability, eligibility and offers can change; confirm them in the provider's current console before purchasing or activating resources. All links below are official and contain no referral codes.

## Start with your budget

Ask your AI to compare a small shortlist using your monthly budget, where you will connect from, intended use and estimated monthly traffic. The [README starting prompts](../README.md#useful-starting-prompts) are the single place to copy an AI request.

This guide covers deployment **outside mainland China**, including Hong Kong, Macao and Taiwan where a provider actually offers the selected product. The five domestic providers below are the project's chosen candidates, not a market ranking. Provider origin and server location are different things. No provider listed here is assumed to offer every region.

For the first comparison, use a plain **Ubuntu 22.04, x86_64** VM with a public IPv4 address, systemd and administrative SSH access. Check the [preparation requirements](#prepare-your-server) before choosing the cheapest plan. A free compute allowance alone does not establish a free, usable setup for this project.

## Five domestic providers

The rows are an unranked shortlist. Compare the actual purchase and renewal totals rather than the advertised discount percentage.

| Provider | Official product | Outside-mainland region examples | Cost details to check |
|---|---|---|---|
| Tencent Cloud | [Lighthouse](https://www.tencentcloud.com/products/lighthouse) | Hong Kong, Singapore, Tokyo; see [regions](https://www.tencentcloud.com/document/product/1103/41266) | Package allowance, renewal, outbound overage and account-site eligibility. |
| Alibaba Cloud | [Simple Application Server](https://www.aliyun.com/product/swas) | Hong Kong, Singapore, Tokyo; see [regions](https://help.aliyun.com/en/simple-application-server/product-overview/regions-and-network-connectivity) | Whether the selected plan includes traffic, bandwidth terms and renewal cost. |
| Volcengine (火山引擎, referred to as 火山云 in discussion) | [Elastic Compute Service](https://www.volcengine.com/product/ecs) | Consult the product's [regions and availability zones](https://docs.volcengine.com/docs/ecs/regions-and-availability-zones?lang=zh) and current console; do not assume its cheapest lightweight offer includes an eligible region. | Instance, disk and public-network charges together; confirm the product and region, not only the promotion. |
| Huawei Cloud | [Flexus L](https://www.huaweicloud.com/intl/en-us/product/flexus-l.html) | Hong Kong, Singapore, Bangkok; see [regions](https://support.huaweicloud.com/intl/en-us/flexusl_faq/faq_01_0006.html) | Included traffic, overage, renewal and account-site eligibility. |
| RainYun (雨云) | [Cloud Server / RCS](https://www.rainyun.com/rcs) | Hong Kong and Los Angeles appear in the official product listing; check current stock and public-IP options in its JavaScript selector. | Select a VM with its own reachable public IPv4; verify traffic, bandwidth, renewal and trial terms for that exact plan. |

The linked account sites can have different offers, payment methods and available regions. Use the official site for your actual account; do not assume a promotion applies across account sites. Current prices and live stock have not been validated through a logged-in purchase session.

## Four international free-tier or trial options

These are opportunities to reduce cost, not four promises of permanently free servers. Check VM eligibility, public IP, disk and traffic together. Functions, static hosting and a browser-only shell do not replace a Linux VM with systemd and reachable SSH.

| Provider and official entry | Offer type | What matters for this project |
|---|---|---|
| [Google Cloud](https://cloud.google.com/free) / Compute Engine | Limited recurring Free Tier **and** a separate time-limited new-user trial | The recurring `e2-micro` allowance is limited to `us-west1`, `us-central1` and `us-east1`; an Asian VM is not covered by that allowance. Outbound allowance has destination exclusions including China and Australia. Check [eligibility and limits](https://docs.cloud.google.com/free/docs/free-cloud-features) and [public IPv4/network charges](https://cloud.google.com/vpc/network-pricing): free compute does not mean an all-day public IPv4 is free. |
| [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) / OCI Compute | Always Free-eligible resources **and** a separate time-limited trial | Eligible compute is tied to the tenancy's home region and available capacity. Confirm the console's eligibility label, current shape, architecture, storage and traffic limits. Arm instances need the matching arm64 package. Read the [resource limits and idle reclamation rules](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) and [FAQ](https://www.oracle.com/cloud/free/faq/); allocation and continuous availability are not guaranteed. |
| [AWS Free Tier](https://aws.amazon.com/free/) / eligible EC2 resources | Time-limited Free plan and credits for eligible new accounts | The current new-account Free plan lasts up to six months or credit exhaustion, whichever comes first. Confirm eligible VM, region, disk, public IPv4 and traffic in the actual account. Account creation date and plan matter; do not reuse an old “12 months of free EC2” tutorial as today's offer. See the [current FAQ](https://aws.amazon.com/free/free-tier-faqs/), including what happens when the Free plan ends. |
| [Microsoft Azure](https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account) / eligible Linux VMs | Introductory credit plus limited monthly amounts of selected services | The introductory trial and eligible 12-month service allowances are different offers. Continuing after trial credit expires requires moving to pay-as-you-go; usage beyond the included quantities can be charged. Confirm the eligible VM, region, disk and public IP together. See [avoiding charges with a free account](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/avoid-charges-free-account). |

**Registration is not guaranteed.** Google requires a valid payment method and identity/payment verification ([signup requirements](https://docs.cloud.google.com/free/docs/free-cloud-features)); Oracle uses contact and card information for identity checks ([FAQ](https://www.oracle.com/cloud/free/faq/)). AWS may request additional verification, including a payment method ([FAQ](https://aws.amazon.com/free/free-tier-faqs/)); Azure describes phone and card verification on its [account page](https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account). Do not describe these services as requiring no identity checks or as easy for every applicant. Complete sensitive verification directly with the provider.

## Compare the cost you will actually pay

Before choosing, ask the AI to summarize **one suitable option per shortlisted provider** with official links, the check date and these items:

- Initial cost, billing period, currency and applicable tax; ongoing renewal cost after discounts or credits end.
- Included outbound traffic, destination exclusions, bandwidth conditions and what happens after the allowance is used.
- Public IPv4, system disk and any separately billed network resources. Avoid adding optional services unless needed.
- For a free offer: eligibility, allowed region and VM shape, expiry, resource reclamation and whether continued use requires a paid upgrade.

If a charge or condition cannot be established, mark it **unknown** rather than treating it as zero. Prefer the lowest ongoing total among options that meet your needs. Do not promise latency or reachability based on geographic proximity alone; actual routes and network conditions differ.

You choose and purchase or activate the server in the official provider console. Neither this guide nor its AI prompt authorizes purchases or paid-account upgrades. Provider budget alerts do not necessarily stop spending; stopping this project's proxy does not cancel cloud billing or release separately billed disks and IPs.

## Prepare your server

| Item | Default preparation path |
|---|---|
| System | A plain Ubuntu 22.04 image with systemd; Debian 12 is another documented first-deployment option. Choose an OS image rather than an app template. |
| Architecture | x86_64 / amd64 by default. The installer also has arm64 packages; verify architecture and compatibility when considering an Arm free-tier VM. |
| Public access | A reachable public IPv4 address, outbound access needed by the installer, and firewall rules for the actual SSH and service ports. NAT-only or IPv6-only plans are outside this default path; do not assume they work unchanged. |
| SSH | Address, username and password or private key. The proposed form defaults to `root`, but retain the provider's actual default user when appropriate. First deployment can run the existing script with `sudo` as root. |
| Permissions and ports | Remote installation currently runs privileged commands directly as the SSH user; a non-root login is not proof of automatic sudo support. The current remote path also uses SSH port 22. Explain these gaps before proceeding; do not silently enable root password login or change SSH configuration. SSH and proxy ports are separate. |
| Capacity | Check available resources and the intended workload. This project has not established a benchmarked minimum CPU or RAM requirement; a vendor's free VM specification is not a project performance guarantee. |

These requirements reflect the current [first-deployment installer](../deploy/install.sh), [remote installer](../server/addnode.sh) and [interaction design capability gaps](设计/客户端Web交互设计规格说明书.md#121-能力对照表). The planned independent read-only Connect flow is not yet a current product capability; inspect safely with available tools before installation instead of using the install job as a read-only check. If an existing plan does not fit, explain the mismatch and options before suggesting a different purchase, reinstall or access change.

## Connect with SSH first

**SSH is the default entry for every provider, including Tencent Cloud.** Prepare the server address and login first. The design places optional `Tencent Cloud` authorization below the SSH form, rather than asking every user to authorize a cloud account before connecting. That placement is specified for future implementation; this documentation update does not change the existing web interface.

Tencent Lighthouse is the only current native cloud API adapter for instance discovery, supported firewall actions and real cloud usage. All other candidates, including Tencent CVM, use generic SSH on a compatible host. They do not gain native discovery, cloud firewall automation or the project's 85% cloud-usage protection just by appearing in this guide. A free-tier label also does not provide those integrations. Cloud API keys and SSH credentials are separate.

Once ready, return to [AI-assisted setup](../README.md#ai-assisted-setup). The AI should identify your chosen machine, inspect before changes, explain current implementation gaps and continue through the project's existing deployment path after you confirm the target and installation. If you already have a compatible server, start there; no new purchase is needed.

[Back to Need a server?](../README.md#need-a-server)
